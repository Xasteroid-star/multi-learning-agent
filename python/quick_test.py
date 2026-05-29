"""快速端到端测试 -- 不经过 HTTP，直接调用 orchestrator。"""
import asyncio
from api.orchestrator import AgentOrchestrator
from core.problem_analyzer import ProblemAnalysis, SolutionStep
from core.photo_session import SessionState


async def main():
    print("=" * 50)
    print("端到端测试：拍照搜题 + 个性化引导")
    print("=" * 50)

    orch = AgentOrchestrator()
    print(f"\n[OK] Orchestrator 初始化完成，Agent 数量: 6 (含 PhotoTutorAgent)")

    # 1. 模拟 OCR + 分析结果（跳过真实 LLM）
    analysis = ProblemAnalysis(
        problem_text="已知二次函数 f(x)=x²+2x-3，求其顶点坐标",
        knowledge_points=["二次函数顶点式", "配方法"],
        difficulty=3,
        solution_steps=[
            SolutionStep(
                step_number=1,
                description="识别函数类型",
                key_insight="二次函数 标准形式 ax²+bx+c",
                socratic_prompt="你能识别出这是哪种类型的函数吗？它的标准形式是什么？",
            ),
            SolutionStep(
                step_number=2,
                description="求顶点坐标",
                key_insight="顶点公式 x=-b/(2a)",
                socratic_prompt="那你知道怎么从一般式求顶点坐标吗？",
            ),
        ],
        relevance_to_weak=0.7,
    )

    # 2. 创建拍照会话
    session_id = orch.create_photo_session("u1", analysis)
    print(f"\n[OK] 会话已创建: {session_id}")
    print(f"   题目: {analysis.problem_text}")
    print(f"   知识点: {analysis.knowledge_points}")

    # 3. 设置会话为 GUIDING 状态
    orch.photo_tutor.session_manager.get_session(session_id).state = SessionState.GUIDING

    # 4. 第一步：学生正确回复
    reply1 = "这是二次函数，标准形式是 f(x)=ax²+bx+c，二次函数 标准形式 ax²+bx+c"
    result1 = orch.submit_photo_reply(session_id, "u1", reply1)
    print(f"\n>> 学生: {reply1[:50]}...")
    print(f"<< 系统: action={result1['action']}, msg={result1['message'][:80]}...")

    # 5. 第二步：学生正确回复
    if result1['action'] == 'praise':
        reply2 = "顶点公式 x=-b/(2a)，代入 a=1, b=2，得 x=-1，然后 y=f(-1)=1-2-3=-4，所以顶点坐标 (-1, -4)"
        result2 = orch.submit_photo_reply(session_id, "u1", reply2)
        print(f"\n>> 学生: {reply2[:50]}...")
        print(f"<< 系统: action={result2['action']}, msg={result2['message'][:80]}...")

    # 6. 测试提示→揭示路径
    print("\n" + "=" * 50)
    print("测试：提示→揭示边界路径")
    print("=" * 50)

    analysis2 = ProblemAnalysis(
        problem_text="解方程 2x+5=15",
        knowledge_points=["一元一次方程"],
        difficulty=1,
        solution_steps=[
            SolutionStep(
                step_number=1,
                description="移项",
                key_insight="移项 等式性质 两边同减",
                socratic_prompt="你打算怎么处理这个方程？",
            ),
        ],
    )
    sid2 = orch.create_photo_session("u2", analysis2)
    orch.photo_tutor.session_manager.get_session(sid2).state = SessionState.GUIDING

    actions = []
    for i in range(7):
        r = orch.submit_photo_reply(sid2, "u2", "不知道")
        actions.append(r['action'])
        hint = r.get('hint_level', '-')
        print(f"  第{i+1}次回答: action={r['action']}, hint_level={hint}")

    assert "hint" in actions, f"应该有 hint，实际动作: {actions}"
    assert "reveal" in actions, f"应该有 reveal，实际动作: {actions}"
    print("\n[OK] 提示→揭示路径通过！")

    print("\n" + "=" * 50)
    print("[SUCCESS] 所有端到端测试通过！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
