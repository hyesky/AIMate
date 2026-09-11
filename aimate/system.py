"""系统装配器：把各层组件组装为可运行的 AIMate 实例（演示/骨架）。"""
from __future__ import annotations

from typing import Optional

from aimate.agents.core import Agent, register
from aimate.gateway.auth.auth import GatewayAuth
from aimate.license.manager import LicenseManager
from aimate.llm.gateway import LLMError, LLMGateway
from aimate.memory.manager import MemoryManagerAsync
from aimate.org.service import Department, Member, OrgService, Role
from aimate.rag.engine import BM25Index, KnowledgeBase
from aimate.security.audit import AuditLog
from aimate.skills.store import Curator, Skill, SkillStatus, SkillStore


class System:
    def __init__(self) -> None:
        self.org = OrgService()
        self.auth = GatewayAuth(self.org)
        self.memory = MemoryManagerAsync(workers=2)
        self.skills = SkillStore()
        self.curator = Curator(self.skills)
        self.audit = AuditLog()
        self.license_mgr = LicenseManager()
        self.rag = KnowledgeBase()          # 默认稀疏检索
        self.llm = LLMGateway()             # 内网推理网关（默认空，按配置装配）
        self.llm_config_path: Optional[str] = None
        self.llm_default = "inner-gateway"
        self.demo_agent: Optional[Agent] = None

    def configure_llm(self, path_or_dict) -> None:
        """从 JSON 配置文件装配内网 LLM 网关。可传路径或直接传 dict。"""
        import json
        if isinstance(path_or_dict, str):
            with open(path_or_dict, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            cfg = path_or_dict
        self.llm.configure(cfg.get("backends", {}))
        self.llm_default = cfg.get("default", self.llm_default)

    def bootstrap_demo(self) -> None:
        tenant = "tenant-demo"

        # 部门 + 成员
        self.org.add_dept(Department("d-root", tenant, "总部"))
        self.org.add_dept(Department("d-it", tenant, "IT 部", "d-root"))
        self.org.add_member(Member("u-admin", tenant, "管理员", Role.ADMIN, "d-root"))
        self.org.add_member(Member("u-1", tenant, "张工", Role.MEMBER, "d-it"))

        # 数字员工
        self.demo_agent = Agent(
            id="it-support",
            name="IT 支持专家",
            tenant_id=tenant,
            role="expert",
            soul_md="# 你是一位严谨的企业 IT 支持专家……",
            skill_names=["knowledge_base", "ticket"],
        )
        register(self.demo_agent)

        # 初始记忆（示范有界记忆 + 自进化产物）
        self.memory.add(tenant, "it-support", "memory",
                        "用户张工偏好中文简洁回复；项目 AIMate 用 Apache-2.0。")

        # 技能
        self.skills.create(Skill(
            name="ticket", tenant_id=tenant, description="工单处理",
            trigger="用户报障时", status=SkillStatus.PUBLISHED, owner="it-support",
        ))

        # License 演示：有效期至 2099 年，开通 rag/workflow 功能
        import time
        self._demo_license = self.license_mgr.load(
            f'{{"issued_at":{int(time.time())},"expires_at":{int(time.time())+86400*365*50},'
            f'"features":["rag","workflow","multi_im"],"max_seats":100}}',
            tenant,
        )

        # RAG 知识库示范
        self.rag.index("AIMate 平台支持私有化内网部署。RAG 知识库支持切分、向量化、召回。"
                       "数字员工可绑定内网推理网关。多租户记忆与技能按组织隔离。",
                       doc_id="doc-aimate")

    def search_kb(self, query: str):
        return self.rag.search(query, top_k=3)


def build_system() -> System:
    return System()
