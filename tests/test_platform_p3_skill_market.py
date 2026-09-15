"""P3 技能市场：企业自建审批流测试（draft → pending_review → published / 驳回退回）。

验证：
 1. 草稿可提交审核：draft → pending_review
 2. 通过：pending_review → published，记录审核意见
 3. 驳回：pending_review → draft（退回），保留驳回意见
 4. 非法迁移被拒：draft 不能直接 review、published 不能再 submit
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.skills.store import SkillStore, Skill, SkillStatus  # noqa: E402

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

    print(f"\nP3 技能市场审批流通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
