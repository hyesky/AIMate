"""P3 技能体系：企业自建审批流 + 自我进化（版本/回滚、Curator 策展）测试。

验证：
 审批流：草稿提交审核 draft→pending_review→published/驳回退回 + 非法迁移拒绝。
 版本回滚：update 保旧快照、version 递增、rollback 恢复上一版、无历史拒滚。
 Curator：system.run_curator 归档闲置 agent 技能、标记陈旧、skip pinned。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from aimate.skills.store import SkillStore, Skill, SkillStatus, Curator  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ✔ {name}")


def fresh():
    return SkillStore()


def main():
    st = fresh()
    st.create(Skill(name="web-automation", tenant_id="t",
                    description="浏览器自动化", trigger="打开网页",
                    status=SkillStatus.DRAFT, owner="enterprise"))
    db = st.get("t", "web-automation")
    check("新建为草稿", db.status == SkillStatus.DRAFT)

    # ---- submit：draft → pending_review ----
    s = st.submit("t", "web-automation")
    check("提交后进入待审", s.status == SkillStatus.PENDING_REVIEW)

    # ---- 非法：处于 pending 时不能再 submit ----
    try:
        st.submit("t", "web-automation")
        check("重复提交被拒", False)
    except ValueError:
        check("重复提交被拒", True)

    # ---- 非草稿直接 review 被拒（尚未 pending）----
    st2 = fresh()
    st2.create(Skill(name="pub", tenant_id="t", status=SkillStatus.PUBLISHED, owner="c"))
    try:
        st2.review("t", "pub", True)
        check("非待审技能不可直接审核", False)
    except ValueError:
        check("非待审技能不可直接审核", True)

    # ---- 通过：pending_review → published，记录意见 ----
    s = st.review("t", "web-automation", True, "合规，准用")
    check("通过后发布", s.status == SkillStatus.PUBLISHED)
    check("记录审核意见", s.review_note == "合规，准用")

    # ---- 驳回退回：新建草稿→提交→驳回→draft + 保留意见 ----
    st3 = fresh()
    st3.create(Skill(name="risky", tenant_id="t", status=SkillStatus.DRAFT, owner="enterprise"))
    st3.submit("t", "risky")
    s = st3.review("t", "risky", False, "涉及数据导出，补充审批")
    check("驳回退回草稿", s.status == SkillStatus.DRAFT)
    check("保留驳回意见", s.review_note == "涉及数据导出，补充审批")

    # ---- 版本与回滚 ----
    stv = fresh()
    stv.create(Skill(name="deploy", tenant_id="t", status=SkillStatus.PUBLISHED,
                     body="# v1", version=1, owner="agent"))
    stv.update("t", "deploy", body="# v2")
    check("update 递增版本", stv.get("t", "deploy").version == 2)
    check("旧版进入历史", len(stv.history("t", "deploy")) == 1)
    stv.update("t", "deploy", description="新描述")
    check("两次 update 两条历史", len(stv.history("t", "deploy")) == 2)
    s = stv.rollback("t", "deploy")
    check("回滚恢复上一版正文", s.body == "# v2" and s.description == "")
    check("回滚后版本还原", s.version == 2)
    s = stv.rollback("t", "deploy")
    check("二次回滚到初始版", s.body == "# v1")
    try:
        stv.rollback("t", "deploy")
        check("无历史拒滚", False)
    except ValueError:
        check("无历史拒滚", True)

    # ---- Curator 后台任务（归档闲置 agent 技能 / 标记陈旧 / skip pinned）----
    stc = fresh()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    stc.create(Skill(name="idle-agent", tenant_id="t", status=SkillStatus.PUBLISHED,
                     owner="agent", last_used_at=old))
    stc.create(Skill(name="idle-pinned", tenant_id="t", status=SkillStatus.PUBLISHED,
                     owner="agent", pinned=True, last_used_at=old))
    stc.create(Skill(name="enterprise-skill", tenant_id="t",
                     status=SkillStatus.PUBLISHED, owner="enterprise", last_used_at=old))
    used_names: set[str] = set()
    cur = Curator(stc, archive_days=90)
    archived = cur.archive_unused("t", used_names)
    check("归档闲置 agent 技能", "idle-agent" in archived)
    check("pinned 技能不归档", "idle-pinned" not in archived)
    check("企业技能不归档", "enterprise-skill" not in archived)
    stale = cur.mark_stale("t", {"idle-agent"})
    check("被使用的不标记陈旧", "idle-agent" not in stale)

    # ---- System.run_curator 端到端（审计记录归档）----
    from aimate.system import System
    sys_ = System()
    sys_.curator = Curator(sys_.skills, archive_days=90)
    old2 = (now - timedelta(days=200)).isoformat()
    sys_.skills.create(Skill(name="moldy", tenant_id="tenant-demo",
                             status=SkillStatus.PUBLISHED, owner="agent",
                             last_used_at=old2))
    res = sys_.run_curator()
    check("run_curator 归档闲置", "moldy" in res["archived"])
    check("归档写入审计", any("skills.auto_archive" == e.action
                              for e in sys_.audit._events))

    # ---- 自我进化闭环：learn prompt 产物经 skill_create 落库为草稿 ----
    from aimate.agents.runner import AgentRunner
    r = AgentRunner(sys_, "dummy")
    out = r._default_executor("skill_create", {
        "name": "web-scrape", "description": "抓取网页正文。",
        "trigger": "抓取/爬取网页", "body": "# 网页抓取\n## 步骤\n1. curl",
    })
    check("skill_create 返回草稿状态", "draft" == out["status"])
    created = sys_.skills.get("tenant-demo", "web-scrape")
    check("技能已入库", created is not None)
    check("agent-created 可被 Curator", created.owner == "agent")
    # description 过长/无句号被拒
    try:
        r._default_executor("skill_create", {
            "name": "bad-desc", "description": "这是一个没有句号且明显超长的描述", "body": "x"})
        check("非法描述被拒", False)
    except Exception:
        check("非法描述被拒", True)

    # ---- P3 员工市场：注册/枚举/启停 ---- 
    from aimate.system import System
    ms = System()
    ms.register_agent("ops-robot", "巡检机器人", role="ops",
                      skill_names=["ticket", "knowledge_base"])
    listed = ms.list_agents()
    check("员工市场列出已注册员工", any(a["id"] == "ops-robot" for a in listed))
    entry = next(a for a in listed if a["id"] == "ops-robot")
    check("员工含角色与技能集", entry["role"] == "ops"
          and "ticket" in entry["skill_names"])
    check("新员工默认在线(IDLE)", entry["status"] == "idle")
    res = ms.set_agent_status("ops-robot", "offline")
    check("停用员工返回 ok", res["ok"] and res["status"] == "offline")
    after = ms.set_agent_status("ops-robot", "active")
    check("重新启用员工", after["ok"] and after["status"] == "idle")
    missing = ms.set_agent_status("nope", "offline")
    check("停用不存在员工失败", not missing["ok"])

    print(f"\nP3 技能体系全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
