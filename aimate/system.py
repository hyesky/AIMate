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
from aimate.mcp.registry import McpRegistry


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
        self.mcp = McpRegistry()            # 内网 MCP 工具库（stdio，数据不出域）
        self.llm_config_path: Optional[str] = None
        self.llm_default = "inner-gateway"
        self.demo_agent: Optional[Agent] = None
        # 会话历史（由 console.serve 注入，供数字员工 search_sessions 召回历史需求）
        self.sessions: Optional[Any] = None

    def search_sessions(self, query: str, owner: str = "default", limit: int = 20
                        ) -> list[dict]:
        """跨会话全文搜索历史消息（FTS5），召回包含 query 的会话与片段。"""
        if self.sessions is None:
            return []
        return self.sessions.search(query, owner, limit)

    def run_curator(self, used_names: set[str] | None = None,
                    tenant_id: str = "tenant-demo") -> dict:
        """手动/后台跑一轮技能策展（自我进化）：归档闲置 + 标记陈旧。

        used_names: 本轮真实被调用的技能名集合（决策引擎可传入）；缺省按
        last_used_at 活动度判定。返回 {archived, stale} 供上层展示/审计。
        """
        used = used_names or set()
        archived = self.curator.archive_unused(tenant_id, used)
        stale = self.curator.mark_stale(tenant_id, used)
        for n in archived:
            self.audit.record("curator", tenant_id, "skills.auto_archive", n)
        return {"archived": archived, "stale": stale}

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

        # 网关 API（供管控台/外部接入复用）
        from aimate.gateway.api.api import GatewayAPI
        self.api = GatewayAPI(self.auth, system=self)

    # ---- 数字员工市场 ----
    def list_agents(self, tenant_id: str = "tenant-demo") -> list[dict]:
        """枚举租户下已注册数字员工（供员工市场列表）。"""
        from aimate.agents.core import list_by_tenant

        return [
            {
                "id": a.id, "name": a.name, "role": a.role,
                "status": a.status.value, "soul_md": a.soul_md,
                "skill_names": list(a.skill_names), "model": a.model,
            }
            for a in list_by_tenant(tenant_id)
        ]

    def register_agent(self, agent_id: str, name: str, tenant_id: str = "tenant-demo",
                       role: str = "employee", soul_md: str = "",
                       skill_names: list[str] | None = None, model: str = "inner-gateway",
                       ) -> "Agent":
        """企业自建数字员工注册（进入员工市场，默认可被调度）。"""
        from aimate.agents.core import Agent, register

        a = Agent(id=agent_id, name=name, tenant_id=tenant_id, role=role,
                  soul_md=soul_md, skill_names=list(skill_names or []), model=model)
        register(a)
        return a

    def set_agent_status(self, agent_id: str, status: str,
                         tenant_id: str = "tenant-demo") -> dict:
        """启停数字员工（online/offline）——员工市场启停按钮后端。"""
        from aimate.agents.core import AgentStatus, get

        a = get(agent_id, tenant_id)
        if not a:
            return {"ok": False, "error": f"数字员工 {agent_id} 不存在"}
        st = AgentStatus.OFFLINE if status in ("offline", "stop", "下线") else AgentStatus.IDLE
        a.status = st
        return {"ok": True, "status": st.value}

    def search_kb(self, query: str):
        return self.rag.search(query, top_k=3)

    # ---- 知识库管理（管控台管理端点复用） ----
    def list_kb_docs(self) -> list[dict]:
        """枚举已索引的文档（按 doc_id 聚合 Chunk 计数与抽样文本）。"""
        docs: dict[str, dict] = {}
        for c in self.rag.bm25.docs:
            d = docs.setdefault(c.doc_id, {"doc_id": c.doc_id, "chunks": 0,
                                           "kind": c.kind, "sample": c.text[:120]})
            d["chunks"] += 1
            if not d["sample"]:
                d["sample"] = c.text[:120]
        return [docs[k] for k in sorted(docs)]

    def add_kb_doc(self, doc_id: str, text: str, kind: str = "doc") -> int:
        return self.rag.index(text, doc_id=doc_id, kind=kind)

    def clear_kb(self) -> int:
        n = len(self.rag.bm25.docs)
        self.rag.bm25.docs.clear()
        self.rag.bm25.df.clear()
        self.rag.bm25.avgdl = 0.0
        if self.rag.vector:
            self.rag.vector.chunks.clear()
            self.rag.vector.vectors.clear()
        return n


def build_system() -> System:
    return System()
