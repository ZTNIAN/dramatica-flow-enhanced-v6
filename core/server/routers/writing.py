"""
/writing 写作+审计+修订（V6 修复版）

修复内容：
- continue_writing / action_write：正确构造 WritingPipeline
- three_layer_audit：正确调用 auditor.audit_chapter
- action_revise：路由路径修复（移除重复前缀）
- 所有端点：添加错误恢复 checkpoint 支持
"""
from __future__ import annotations

import json
import logging
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..deps import (
    sm, load_env, create_llm, run_sync, dc_to_dict,
    ContinueWritingReq, SegmentRewriteReq, ThreeLayerAuditReq,
)

router = APIRouter(prefix="/api/books", tags=["writing"])


def _build_pipeline(s, llm=None):
    """构造 WritingPipeline 的公共逻辑（V6 修复）"""
    from core.pipeline import WritingPipeline, PipelineConfig
    from core.narrative import NarrativeEngine
    from core.agents import (
        ArchitectAgent, WriterAgent, AuditorAgent, ReviserAgent,
        SummaryAgent, PatrolAgent,
        DialogueExpert, EmotionCurveDesigner, CharacterGrowthExpert,
        FeedbackExpert, StyleConsistencyChecker, SceneArchitect,
        PsychologicalPortrayalExpert, MiroFishReader,
    )
    from core.validators import PostWriteValidator
    from core.quality_dashboard import QualityDashboard
    from core.dynamic_planner import DynamicPlanner
    from core.kb_incentive import KBIncentiveTracker
    from core.setup import SetupLoader
    from ..deps import PROJECT_ROOT

    if llm is None:
        llm = create_llm()

    # 加载书籍状态
    try:
        state = SetupLoader.restore(str(PROJECT_ROOT), s.book_id)
    except Exception:
        # fallback：手动读取配置
        try:
            cfg = s.read_config()
        except FileNotFoundError:
            raise HTTPException(404, f"书籍不存在：{s.book_id}")
        state = None

    # 确定主角
    all_chars = list(state.characters.values()) if state else []
    protagonist = None
    if state:
        pid = state.config.protagonist_id
        if pid in state.characters:
            protagonist = state.characters[pid]
        else:
            for c in all_chars:
                if getattr(c, "role", "") in ("protagonist", "主角"):
                    protagonist = c
                    break
            if not protagonist and all_chars:
                protagonist = all_chars[0]

    if not protagonist:
        raise HTTPException(400, "书籍缺少角色配置，请先运行 setup load")

    # 创建各组件
    auditor_llm = create_llm(temperature=0.0, model_env="AUDITOR_MODEL")
    engine = NarrativeEngine(llm)
    config = PipelineConfig.from_env()

    style_guide = ""
    genre = "玄幻"
    forbidden_words = []
    if state:
        style_guide = state.config.style_guide
        genre = state.config.genre
        forbidden_words = state.config.custom_forbidden_words

    pipeline = WritingPipeline(
        state_manager=s,
        architect=ArchitectAgent(llm),
        writer=WriterAgent(llm, style_guide=style_guide, genre=genre),
        auditor=AuditorAgent(auditor_llm),
        reviser=ReviserAgent(llm),
        narrative_engine=engine,
        summary_agent=SummaryAgent(llm),
        validator=PostWriteValidator(forbidden_words),
        protagonist=protagonist,
        all_characters=all_chars,
        patrol=PatrolAgent(llm),
        dashboard=QualityDashboard(),
        dynamic_planner=DynamicPlanner() if (s.book_dir / "dynamic_planner.json").exists() else None,
        kb_tracker=KBIncentiveTracker(),
        # V4 增强 Agent
        dialogue_expert=DialogueExpert(llm),
        emotion_curve_designer=EmotionCurveDesigner(llm),
        character_growth_expert=CharacterGrowthExpert(llm),
        feedback_expert=FeedbackExpert(llm),
        style_checker=StyleConsistencyChecker(llm),
        scene_architect=SceneArchitect(llm),
        psychological_expert=PsychologicalPortrayalExpert(llm),
        mirofish_reader=MiroFishReader(llm),
        config=config,
    )

    # WebSocket 进度回调（延迟导入避免循环依赖）
    try:
        import importlib
        _server = importlib.import_module("core.server")
        _ws = getattr(_server, "ws_manager", None)
        if _ws:
            pipeline.set_progress_callback(
                lambda data: asyncio.ensure_future(_ws.broadcast(s.book_id, data))
            )
    except Exception:
        pass

    return pipeline, all_chars


def _get_next_chapter(s) -> int:
    """获取下一章号"""
    try:
        ws = s.read_world_state()
        return (ws.current_chapter or 0) + 1
    except Exception:
        return 1


@router.post("/{book_id}/continue-writing")
async def continue_writing(book_id: str, req: ContinueWritingReq):
    """续写指定数量的章节（V6 修复版）"""
    load_env()
    s = sm(book_id)
    try:
        s.read_config()
    except FileNotFoundError:
        raise HTTPException(404, f"书籍不存在：{book_id}")

    from core.narrative import ChapterOutlineSchema
    from ..deps import PROJECT_ROOT

    # 加载章纲
    chapter_outlines_path = s.state_dir / "chapter_outlines.json"
    if not chapter_outlines_path.exists():
        raise HTTPException(400, "章纲不存在，请先生成大纲")

    raw = json.loads(chapter_outlines_path.read_text(encoding="utf-8"))
    from core.llm import _fix_df
    for r in raw:
        if r.get("dramatic_function"):
            r["dramatic_function"] = _fix_df(r["dramatic_function"])
        for bi, beat in enumerate(r.get("beats", [])):
            if not beat.get("id"):
                beat["id"] = f"beat_{r.get('chapter_number', bi)}_{bi+1}"
            if beat.get("dramatic_function"):
                beat["dramatic_function"] = _fix_df(beat["dramatic_function"])
    all_outlines = [ChapterOutlineSchema.model_validate(r) for r in raw]

    pipeline, _ = _build_pipeline(s)
    next_ch = _get_next_chapter(s)

    # V6: 加载上一次的 checkpoint（如有）
    checkpoint_path = s.book_dir / "pipeline_checkpoint.json"
    start_offset = 0
    if checkpoint_path.exists():
        try:
            ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if ckpt.get("status") == "interrupted":
                start_offset = ckpt.get("completed_count", 0)
                logging.info(f"[V6] 从 checkpoint 恢复：已完成 {start_offset} 章")
        except Exception:
            pass

    results = []
    for i in range(start_offset, req.count):
        ch_num = next_ch + i
        if ch_num > len(all_outlines):
            results.append({"chapter": ch_num, "status": "all_done"})
            break

        # V6: 写 checkpoint
        try:
            checkpoint_path.write_text(json.dumps({
                "status": "running",
                "total": req.count,
                "completed_count": i,
                "current_chapter": ch_num,
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        co = all_outlines[ch_num - 1]
        try:
            result = await run_sync(pipeline.run, co, False)
            results.append({
                "chapter": ch_num,
                "title": co.title,
                "ok": True,
                "audit_passed": result.audit_report.passed,
                "revision_rounds": result.revision_rounds,
                "word_count": result.word_count,
                "causal_links": result.causal_links,
                "total_rework": result.total_rework_count,
            })
        except Exception as e:
            logging.error(f"续写第 {ch_num} 章失败: {e}", exc_info=True)
            results.append({"chapter": ch_num, "error": str(e)})
            # V6: 中断时保存 checkpoint
            try:
                checkpoint_path.write_text(json.dumps({
                    "status": "interrupted",
                    "total": req.count,
                    "completed_count": i,
                    "failed_chapter": ch_num,
                    "error": str(e),
                }, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            break  # 中断后停止，保留 checkpoint 供恢复

    # V6: 完成后清除 checkpoint
    if len(results) == req.count or all(r.get("ok") or r.get("status") == "all_done" for r in results):
        try:
            if checkpoint_path.exists():
                checkpoint_path.write_text(json.dumps({"status": "completed"}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return {"ok": True, "results": results}


@router.post("/{book_id}/three-layer-audit")
async def three_layer_audit(book_id: str, req: ThreeLayerAuditReq):
    """三层审计（V6 修复版）"""
    load_env()
    s = sm(book_id)
    from core.agents import AuditorAgent, ArchitectBlueprint, PreWriteChecklist, PostWriteSettlement

    llm = create_llm(temperature=0.0, model_env="AUDITOR_MODEL")
    auditor = AuditorAgent(llm)

    content = s.read_final(req.chapter) or s.read_draft(req.chapter)
    if not content:
        raise HTTPException(404, f"第 {req.chapter} 章不存在")

    # 构造 blueprint（从章纲读取，或使用空默认值）
    from core.narrative import ChapterOutlineSchema
    from core.types.state import TruthFileKey

    blueprint = ArchitectBlueprint(
        core_conflict="",
        hooks_to_advance=[],
        hooks_to_plant=[],
        emotional_journey={},
        chapter_end_hook="",
        pace_notes="",
        pov_character_id="",
        pre_write_checklist=PreWriteChecklist([], [], [], [], ""),
    )

    # 尝试从章纲获取更完整的信息
    outline_path = s.state_dir / "chapter_outlines.json"
    if outline_path.exists():
        try:
            outlines = json.loads(outline_path.read_text(encoding="utf-8"))
            for co in outlines:
                if co.get("chapter_number") == req.chapter:
                    blueprint = ArchitectBlueprint(
                        core_conflict=co.get("summary", ""),
                        hooks_to_advance=co.get("hooks_to_advance", []),
                        hooks_to_plant=co.get("hooks_to_plant", []),
                        emotional_journey=co.get("emotional_arc", {}),
                        chapter_end_hook=co.get("chapter_end_hook", ""),
                        pace_notes=co.get("pace_notes", ""),
                        pov_character_id=co.get("pov_character_id", ""),
                        pre_write_checklist=PreWriteChecklist([], [], [], [], ""),
                    )
                    break
        except Exception:
            pass

    truth_ctx = s.read_truth_bundle([
        TruthFileKey.CURRENT_STATE,
        TruthFileKey.CHARACTER_MATRIX,
        TruthFileKey.PENDING_HOOKS,
    ])

    settlement = PostWriteSettlement([], [], [], [], [])

    try:
        report = await run_sync(
            auditor.audit_chapter,
            content, req.chapter, blueprint, truth_ctx, settlement,
            cross_thread_context="",
        )
        return {"ok": True, "report": dc_to_dict(report), "chapter": req.chapter}
    except Exception as e:
        raise HTTPException(500, f"审计失败：{e}")


@router.post("/{book_id}/revise")
async def action_revise(book_id: str, chapter: int = Query(...), mode: str = Query("spot-fix")):
    """手动触发修订（V6 修复版：修正路由路径）"""
    load_env()
    s = sm(book_id)
    from core.agents import ReviserAgent, AuditorAgent, ArchitectBlueprint, PreWriteChecklist, PostWriteSettlement
    from core.types.state import TruthFileKey

    content = s.read_final(chapter) or s.read_draft(chapter)
    if not content:
        raise HTTPException(404, f"第 {chapter} 章不存在")

    llm = create_llm()
    reviser = ReviserAgent(llm)

    # 先审计获取 issues
    auditor_llm = create_llm(temperature=0.0, model_env="AUDITOR_MODEL")
    auditor = AuditorAgent(auditor_llm)
    blueprint = ArchitectBlueprint(
        core_conflict="", hooks_to_advance=[], hooks_to_plant=[],
        emotional_journey={}, chapter_end_hook="", pace_notes="",
        pov_character_id="",
        pre_write_checklist=PreWriteChecklist([], [], [], [], ""),
    )
    truth_ctx = s.read_truth_bundle([TruthFileKey.CURRENT_STATE, TruthFileKey.PENDING_HOOKS])
    settlement = PostWriteSettlement([], [], [], [], [])

    try:
        report = await run_sync(auditor.audit_chapter, content, chapter, blueprint, truth_ctx, settlement,
                                 cross_thread_context="")
        result = await run_sync(reviser.revise, content, report.issues, mode)
        s.save_draft(chapter, result.content)
        s.save_final(chapter, result.content)
        return {"ok": True, "changes": result.changes_summary, "issues_count": len(report.issues)}
    except Exception as e:
        raise HTTPException(500, f"修订失败：{e}")


@router.get("/{book_id}/audit-results/{chapter}")
def get_audit_result(book_id: str, chapter: int):
    s = sm(book_id)
    path = s.state_dir / "audits" / f"audit_ch{chapter:04d}.json"
    if not path.exists():
        raise HTTPException(404, f"第 {chapter} 章审计结果不存在")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{book_id}/audit-results")
def list_audit_results(book_id: str):
    s = sm(book_id)
    audit_dir = s.state_dir / "audits"
    if not audit_dir.exists():
        return []
    results = []
    for f in sorted(audit_dir.glob("audit_ch*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except Exception:
            pass
    return results


@router.post("/{book_id}/ai-rewrite-segment")
async def ai_rewrite_segment(book_id: str, req: SegmentRewriteReq):
    """AI 重写指定段落"""
    load_env()
    s = sm(book_id)
    content = s.read_final(req.chapter) or s.read_draft(req.chapter)
    if not content:
        raise HTTPException(404, f"第 {req.chapter} 章不存在")

    lines = content.split("\n")
    start = max(0, req.start_line - 1)
    end = min(len(lines), req.end_line)
    segment = "\n".join(lines[start:end])
    if not segment.strip():
        raise HTTPException(400, "选中段落为空")

    from core.agents import ReviserAgent
    llm = create_llm()
    reviser = ReviserAgent(llm)
    try:
        result = await run_sync(reviser.revise, segment, [], mode="spot-fix")
        new_lines = lines[:start] + result.content.split("\n") + lines[end:]
        new_content = "\n".join(new_lines)
        s.save_draft(req.chapter, new_content)
        return {"ok": True, "old_segment": segment, "new_segment": result.content, "changes": result.changes_summary}
    except Exception as e:
        raise HTTPException(500, f"重写失败：{e}")


@router.put("/{book_id}/chapters/{chapter}/content")
def update_chapter_content(book_id: str, chapter: int, req: dict):
    content = req.get("content", "")
    kind = req.get("kind", "draft")
    if not content:
        raise HTTPException(400, "内容不能为空")
    s = sm(book_id)
    s.save_draft(chapter, content)
    if kind == "final":
        s.save_final(chapter, content)
    return {"ok": True, "chars": len(content)}


@router.post("/{book_id}/write")
async def action_write(book_id: str, count: int = Query(1)):
    """触发写作（V6 修复版：正确构造 pipeline）"""
    load_env()
    s = sm(book_id)
    try:
        s.read_config()
    except FileNotFoundError:
        raise HTTPException(404, f"书籍不存在：{book_id}")

    from core.narrative import ChapterOutlineSchema
    from core.llm import _fix_df

    # 加载章纲
    chapter_outlines_path = s.state_dir / "chapter_outlines.json"
    if not chapter_outlines_path.exists():
        raise HTTPException(400, "章纲不存在，请先生成大纲")

    raw = json.loads(chapter_outlines_path.read_text(encoding="utf-8"))
    for r in raw:
        if r.get("dramatic_function"):
            r["dramatic_function"] = _fix_df(r["dramatic_function"])
        for bi, beat in enumerate(r.get("beats", [])):
            if not beat.get("id"):
                beat["id"] = f"beat_{r.get('chapter_number', bi)}_{bi+1}"
            if beat.get("dramatic_function"):
                beat["dramatic_function"] = _fix_df(beat["dramatic_function"])
    all_outlines = [ChapterOutlineSchema.model_validate(r) for r in raw]

    pipeline, _ = _build_pipeline(s)
    next_ch = _get_next_chapter(s)

    def _write_sync():
        results = []
        for i in range(count):
            ch_num = next_ch + i
            if ch_num > len(all_outlines):
                results.append({"chapter": ch_num, "status": "all_done"})
                break
            co = all_outlines[ch_num - 1]
            try:
                result = pipeline.run(co, False)
                results.append({
                    "chapter": ch_num, "ok": True,
                    "audit_passed": result.audit_report.passed,
                    "word_count": result.word_count,
                })
            except Exception as e:
                results.append({"chapter": ch_num, "error": str(e)})
        return results

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _write_sync)
    return {"ok": True, "results": results}


@router.post("/{book_id}/audit")
async def action_audit(book_id: str, chapter: int = Query(...)):
    """触发审计（V6 修复版）"""
    load_env()
    s = sm(book_id)
    from core.agents import AuditorAgent, ArchitectBlueprint, PreWriteChecklist, PostWriteSettlement
    from core.types.state import TruthFileKey

    content = s.read_final(chapter) or s.read_draft(chapter)
    if not content:
        raise HTTPException(404, f"第 {chapter} 章不存在")

    llm = create_llm(temperature=0.0, model_env="AUDITOR_MODEL")
    auditor = AuditorAgent(llm)
    blueprint = ArchitectBlueprint(
        core_conflict="", hooks_to_advance=[], hooks_to_plant=[],
        emotional_journey={}, chapter_end_hook="", pace_notes="",
        pov_character_id="",
        pre_write_checklist=PreWriteChecklist([], [], [], [], ""),
    )
    truth_ctx = s.read_truth_bundle([
        TruthFileKey.CURRENT_STATE, TruthFileKey.PENDING_HOOKS,
    ])
    settlement = PostWriteSettlement([], [], [], [], [])

    def _audit_sync():
        return auditor.audit_chapter(content, chapter, blueprint, truth_ctx, settlement,
                                      cross_thread_context="")

    try:
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, _audit_sync)
        return {
            "ok": True,
            "chapter": chapter,
            "passed": report.passed,
            "issues": len(report.issues),
            "weighted_total": report.weighted_total,
            "critical_count": report.critical_count,
            "warning_count": report.warning_count,
            "dimension_scores": report.dimension_scores,
        }
    except Exception as e:
        raise HTTPException(500, f"审计失败：{e}")


# ── V6: 错误恢复端点 ─────────────────────────────────────────────────────────

@router.get("/{book_id}/checkpoint")
def get_checkpoint(book_id: str):
    """获取当前 checkpoint 状态（V6 新增）"""
    s = sm(book_id)
    checkpoint_path = s.book_dir / "pipeline_checkpoint.json"
    if not checkpoint_path.exists():
        return {"status": "none"}
    try:
        return json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "corrupt"}


@router.post("/{book_id}/resume")
async def resume_from_checkpoint(book_id: str):
    """从 checkpoint 恢复写作（V6 新增）"""
    load_env()
    s = sm(book_id)
    checkpoint_path = s.book_dir / "pipeline_checkpoint.json"
    if not checkpoint_path.exists():
        raise HTTPException(400, "没有可恢复的 checkpoint")

    try:
        ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(400, "checkpoint 文件损坏")

    if ckpt.get("status") != "interrupted":
        raise HTTPException(400, f"checkpoint 状态不是 interrupted（当前：{ckpt.get('status')}）")

    total = ckpt.get("total", 1)
    completed = ckpt.get("completed_count", 0)

    # 继续写作剩余章节
    remaining = total - completed
    req = ContinueWritingReq(count=remaining)
    return await continue_writing(book_id, req)


# ── V6: 旧路径兼容（前端可能仍调用 /api/action/*）─────────────────────────────

@router.post("/api/action/write")
async def legacy_action_write(book_id: str = Query(...), count: int = Query(1)):
    """旧路径兼容：/api/action/write → /{book_id}/write"""
    logging.warning("[deprecated] /api/action/write 已弃用，请改用 /{book_id}/write")
    return await action_write(book_id, count)


@router.post("/api/action/audit")
async def legacy_action_audit(book_id: str = Query(...), chapter: int = Query(...)):
    """旧路径兼容：/api/action/audit → /{book_id}/audit"""
    logging.warning("[deprecated] /api/action/audit 已弃用，请改用 /{book_id}/audit")
    return await action_audit(book_id, chapter)


@router.post("/api/action/revise")
async def legacy_action_revise(
    book_id: str = Query(...),
    chapter: int = Query(...),
    mode: str = Query("spot-fix"),
):
    """旧路径兼容：/api/action/revise → /{book_id}/revise"""
    logging.warning("[deprecated] /api/action/revise 已弃用，请改用 /{book_id}/revise")
    return await action_revise(book_id, chapter, mode)
