"""版本化 clickwrap 条款文档与一致性校验。

这里提供的是产品可审计的电子同意机制，不替代针对实际运营主体、所在地和
业务模式的律师审阅。条款正文作为代码版本的一部分冻结，数据库只记录版本和
摘要，从而避免事后静默改写用户已经接受的内容。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

LegalLocale = Literal["en", "zh-CN"]

CURRENT_TERMS_VERSION = "2026-07-29-v2"
CURRENT_TERMS_EFFECTIVE_DATE = date(2026, 7, 29)
MINIMUM_ACCOUNT_AGE = 18


class LegalSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    body: tuple[str, ...]


class LegalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: str = "1.0.0"
    version: str
    effectiveDate: date
    locale: LegalLocale
    title: str
    summary: str
    operatorLabel: str
    minimumAge: int
    sections: tuple[LegalSection, ...]
    acceptanceStatements: tuple[str, ...]
    legalReviewNotice: str
    documentHash: str = ""


_EN_SECTIONS = (
    LegalSection(
        id="scope",
        title="1. Scope, operator, and acceptance",
        body=(
            "These Terms of Use and Privacy Notice (the “Terms”) govern access to and use "
            "of EventShock Lab, including its website, accounts, APIs, simulations, AI-assisted "
            "features, exports, documentation, and related services (collectively, the "
            "“Service”). “Operator” means the EventShock Lab project operators identified "
            "through the project repository or an applicable deployment notice.",
            "By creating an account, selecting every required acceptance control, or continuing "
            "to use the Service after a required re-acceptance notice, you affirmatively agree "
            "to the version displayed to you. If you do not agree, do not create an account and "
            "do not use the authenticated Service. Headings are for convenience and do not "
            "limit the meaning of any provision. You consent to receive this agreement and "
            "related notices electronically, may print or save the displayed copy before "
            "accepting, and intend the required checkboxes and final acceptance action to serve "
            "as your electronic signature to the extent permitted by applicable law.",
        ),
    ),
    LegalSection(
        id="eligibility",
        title="2. Eligibility and account responsibility",
        body=(
            "You must be at least 18 years old and legally capable of entering an agreement. "
            "The Service is not directed to children. You must provide an email address you are "
            "authorized to use, keep credentials confidential, and promptly report suspected "
            "account compromise. You are responsible for activity performed through your "
            "account unless applicable law provides otherwise.",
            "You may not share verification codes, evade access controls, impersonate another "
            "person, create accounts through automated abuse, or use another person’s API key. "
            "The Operator may suspend an account when reasonably necessary to protect the "
            "Service, users, evidence integrity, or legal compliance.",
        ),
    ),
    LegalSection(
        id="research-boundary",
        title="3. Research-only boundary; no prediction or advice",
        body=(
            "EventShock Lab is an educational and research scenario-analysis tool. Outputs are "
            "conditional on synthetic agents, selected evidence, model versions, simulation "
            "assumptions, random seeds, and user-supplied parameters. They are not forecasts of "
            "market prices or events and are not investment, legal, accounting, tax, compliance, "
            "or other professional advice.",
            "You must independently verify sources and results and obtain appropriate qualified "
            "advice before making consequential decisions. You may not present an output as a "
            "guaranteed outcome, an official finding, or a recommendation to buy, sell, hold, "
            "size, or time a financial position.",
        ),
    ),
    LegalSection(
        id="human-review",
        title="4. AI assistance and mandatory human review",
        body=(
            "AI features may extract candidate claims, propose fields, summarize results, plan "
            "bounded reads, or suggest workflow steps. AI output can be incomplete, inaccurate, "
            "biased, outdated, fabricated, or inconsistent. Search results and third-party "
            "content are candidate evidence, not verified facts.",
            "You retain control and responsibility. Before an Event Pack, scenario, export, or "
            "other artifact is frozen or used, you must inspect the underlying sources, edit or "
            "reject unsupported content, confirm timing and provenance, and make the explicit "
            "human approval required by the interface. AI never has authority to make trades, "
            "bypass controls, or bind you or the Operator.",
        ),
    ),
    LegalSection(
        id="byok",
        title="5. Third-party models, search, and bring-your-own-key use",
        body=(
            "When you configure a third-party model or search provider, the Service may transmit "
            "bounded prompts, selected source fragments, experiment result slices, and your "
            "related requests to that provider. The provider’s own terms, privacy practices, "
            "availability, geographic restrictions, safety filters, and fees apply separately. "
            "The Operator does not control or endorse those services.",
            "API keys are intended to remain in volatile server memory for a limited session and "
            "are not associated with your persistent account record. Nevertheless, you must use "
            "a restricted key where available, monitor provider billing, avoid entering secrets "
            "into content fields, and revoke a key if exposure is suspected. You authorize "
            "charges caused by requests you confirm through the Service.",
        ),
    ),
    LegalSection(
        id="user-content",
        title="6. User content, sources, and permissions",
        body=(
            "You retain any rights you hold in text, URLs, datasets, prompts, claims, and other "
            "materials you submit (“User Content”). You grant the Operator a non-exclusive, "
            "worldwide, royalty-free license to host, reproduce, transform, transmit, and display "
            "User Content only as reasonably necessary to operate, secure, troubleshoot, and "
            "improve the Service for you and authorized users.",
            "You represent that you have all permissions needed to submit and process User "
            "Content. Do not upload confidential information, personal data, paywalled material, "
            "malware, unlawfully obtained data, or copyrighted works beyond your lawful rights. "
            "Source URLs, quotations, licenses, timestamps, and provenance must not be removed or "
            "misrepresented.",
        ),
    ),
    LegalSection(
        id="acceptable-use",
        title="7. Acceptable use and prohibited conduct",
        body=(
            "You may not use the Service to violate law or third-party rights; facilitate fraud, "
            "market manipulation, harassment, discrimination, surveillance, credential theft, "
            "malware, or weapons harm; generate deceptive financial promotion; probe other users’ "
            "data; defeat rate limits; exploit prompt injection; extract protected system "
            "instructions or secrets; or interfere with service availability.",
            "Security research must be authorized, proportionate, and reported responsibly. You "
            "must not publish exploit details, personal information, credentials, or sensitive "
            "logs in a public issue. The Operator may remove harmful content and preserve limited "
            "records when reasonably required for security, audit, or legal obligations.",
        ),
    ),
    LegalSection(
        id="privacy",
        title="8. Privacy notice and data handling",
        body=(
            "An email address is personal information. The Service stores the account email, "
            "password hashes, email-verification status, "
            "session records, acceptance records, self-selected experience preferences, audit "
            "events, Event Packs, scenarios, experiments, exports, and AI-related conversation "
            "records needed to provide continuity and accountability. Passwords and verification "
            "codes are not stored in plaintext. The account email is used only for account "
            "access, verification, security, support, and research-data ownership; it is not "
            "included in prompts sent to AI or search providers. Sensitive content should not "
            "be submitted.",
            "Data is used to authenticate users, provide and personalize workflows, run requested "
            "analysis, preserve reproducibility, prevent abuse, diagnose failures, and operate "
            "the Service. Limited data is disclosed to infrastructure and AI/search providers "
            "only when needed for requested functions. The Service does not promise that a "
            "third-party provider will process data in your country.",
            "Authentication cookies and browser storage are used for session security, language, "
            "theme, temporary API configuration, and workflow continuity. An authenticated user "
            "may export the account data currently held by the primary database or request "
            "account deletion through the in-product Account and privacy page after re-entering "
            "the current password. Deletion removes active account-owned records and signs the "
            "user out, but encrypted or access-controlled backups may retain a copy until their "
            "scheduled expiry where immediate selective deletion is not technically possible. "
            "Security, fraud-prevention, or legal records may be retained only where reasonably "
            "necessary. Other requests must use an operator-provided private channel; never put "
            "sensitive information in a public repository issue.",
            "Reverse-proxy and traffic-statistics logs may temporarily process network address, "
            "request time, path, status, device or browser user-agent, and similar connection "
            "metadata for security, rate limiting, incident response, and aggregate operations. "
            "Authentication cookies, authorization headers, CSRF tokens, session identifiers, "
            "and API keys are excluded or redacted from managed access-log formats. Operational "
            "logs remain subject to server rotation and access controls.",
        ),
    ),
    LegalSection(
        id="security",
        title="9. Security, availability, and changes",
        body=(
            "Reasonable safeguards are used, but no online service, model, search engine, or "
            "storage system is guaranteed secure, uninterrupted, or error-free. Maintenance, "
            "provider outages, model changes, quotas, attacks, or experimental software may "
            "delay, alter, or remove functionality. You are responsible for preserving exports "
            "needed for your work.",
            "The Operator may modify the Service and may require acceptance of a new Terms "
            "version before further authenticated use. Material changes will be presented "
            "conspicuously in the interface. Continuing only after affirmative acceptance records "
            "agreement to the displayed version; silence alone is not acceptance.",
        ),
    ),
    LegalSection(
        id="intellectual-property",
        title="10. Project software and intellectual property",
        body=(
            "The project software is made available only under the license identified in the "
            "repository LICENSE file. Public source visibility does not grant rights beyond that "
            "license. Product names, marks, hosted data, third-party models, and third-party "
            "content may be governed by separate rights.",
            "Except for the limited User Content license above, these Terms do not transfer "
            "ownership. Feedback may be used without restriction or compensation, provided the "
            "Operator does not intentionally publish confidential information identified as such "
            "through an authorized private channel.",
        ),
    ),
    LegalSection(
        id="disclaimers",
        title="11. Disclaimers and allocation of risk",
        body=(
            "TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE SERVICE IS PROVIDED “AS IS” "
            "AND “AS AVAILABLE,” WITHOUT WARRANTIES OF ACCURACY, FITNESS FOR A PARTICULAR "
            "PURPOSE, MERCHANTABILITY, NON-INFRINGEMENT, AVAILABILITY, OR RESULTS. NOTHING IN "
            "THESE TERMS EXCLUDES A WARRANTY OR RIGHT THAT CANNOT LAWFULLY BE EXCLUDED.",
            "TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE OPERATOR WILL NOT BE LIABLE "
            "FOR INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, CONSEQUENTIAL, OR PUNITIVE DAMAGES, "
            "OR FOR LOST PROFITS, TRADING LOSSES, LOST DATA, OR BUSINESS INTERRUPTION ARISING "
            "FROM THE SERVICE. ANY NON-EXCLUDABLE LIABILITY REMAINS LIMITED ONLY TO THE EXTENT "
            "THE LAW ALLOWS.",
        ),
    ),
    LegalSection(
        id="indemnity-termination",
        title="12. Indemnity, suspension, termination, and general terms",
        body=(
            "To the extent permitted by law, you will defend and indemnify the Operator from "
            "third-party claims arising from your unlawful User Content, violation of these "
            "Terms, misuse of third-party services, or infringement of another person’s rights. "
            "This obligation does not apply to the extent a claim was caused by the Operator’s "
            "own unlawful conduct.",
            "You may stop using the Service at any time. The Operator may suspend or terminate "
            "access for material breach, security risk, legal obligation, or discontinuation. "
            "Provisions that by their nature should survive—including ownership, disclaimers, "
            "risk allocation, audit integrity, and accrued obligations—survive termination.",
            "If a provision is unenforceable, it will be limited to the minimum extent necessary "
            "and the remainder remains effective. Failure to enforce a provision is not a waiver. "
            "Applicable law governs without displacing mandatory protections that apply to you. "
            "These Terms, the displayed Privacy Notice, and incorporated notices are the entire "
            "agreement about the Service unless a signed written agreement states otherwise.",
        ),
    ),
)

_ZH_SECTIONS = (
    LegalSection(
        id="scope",
        title="1. 适用范围、运营方与同意方式",
        body=(
            "本《使用条款与隐私告知》（下称“本条款”）适用于 EventShock Lab 网站、账户、API、"
            "模拟、AI 辅助功能、导出、文档及相关服务（合称“本服务”）。“运营方”是指项目仓库"
            "或相关部署通知中标明的 EventShock Lab 项目运营者。",
            "当您创建账户、勾选全部必选同意项，或在版本更新后完成重新同意，即表示您以明确"
            "的电子行为同意页面所示版本。如不同意，请勿创建账户或继续使用需登录的服务。标题"
            "仅为阅读便利，不限制各条款含义。您同意以电子方式接收本协议及相关通知，可在接受"
            "前打印或保存页面所示副本，并在适用法律允许的范围内，明确意图将必选勾选动作及"
            "最终“同意并继续”操作作为您的电子签名。",
        ),
    ),
    LegalSection(
        id="eligibility",
        title="2. 使用资格与账户责任",
        body=(
            "您必须年满 18 周岁并具备订立协议的法律能力；本服务不面向儿童。您应使用有权控制"
            "的邮箱，妥善保管密码与验证码，并及时报告疑似账户泄露。除适用法律另有规定外，您"
            "对经由本人账户实施的活动负责。",
            "您不得共享验证码、规避访问控制、冒充他人、批量滥用注册或使用他人的 API 密钥。"
            "为保护服务、用户、证据完整性或履行法律义务，运营方可在合理必要范围内暂停账户。",
        ),
    ),
    LegalSection(
        id="research-boundary",
        title="3. 仅限研究与教学；不构成预测或建议",
        body=(
            "EventShock Lab 是教学和研究型情景分析工具。所有输出均以合成 Agent、所选证据、"
            "模型版本、模拟假设、随机种子及用户参数为条件，不是市场价格或事件预测，也不构成"
            "投资、法律、会计、税务、合规或其他专业建议。",
            "在作出有后果的决定前，您必须独立核验来源和结果并寻求适当的专业意见。您不得把"
            "输出宣传为必然结果、官方结论，或任何买入、卖出、持有、仓位和时机建议。",
        ),
    ),
    LegalSection(
        id="human-review",
        title="4. AI 辅助与强制人工复核",
        body=(
            "AI 功能可能提取候选主张、建议字段、解释结果、规划受限读取或建议工作流步骤。AI "
            "输出可能不完整、不准确、有偏见、过时、虚构或相互矛盾；搜索结果和第三方内容只是"
            "候选证据，不是已验证事实。",
            "控制权和责任始终由您保留。在冻结或使用事件包、情景、导出及其他工件前，您必须"
            "检查原始来源，编辑或拒绝无支持内容，核对时间与出处，并完成界面要求的明确人工"
            "批准。AI 无权交易、绕过控制或代表您或运营方作出承诺。",
        ),
    ),
    LegalSection(
        id="byok",
        title="5. 第三方模型、联网搜索与自带密钥",
        body=(
            "当您配置第三方模型或搜索服务时，本服务可能向该供应商传输受限提示词、已选择的"
            "来源片段、实验结果切片及相关请求。该供应商自己的条款、隐私规则、可用性、地域"
            "限制、安全过滤和费用另行适用；运营方不控制或背书其服务。",
            "API 密钥按设计仅在有限会话的服务器易失性内存中存在，不与持久账户资料绑定。您"
            "仍应尽量使用受限密钥、监控供应商账单、避免在内容字段输入秘密，并在疑似泄露时"
            "及时撤销。您确认由本人在本服务中批准的请求可能产生供应商费用。",
        ),
    ),
    LegalSection(
        id="user-content",
        title="6. 用户内容、来源与授权",
        body=(
            "您保留对所提交文字、网址、数据、提示、主张及其他材料（“用户内容”）依法享有的"
            "权利。您授予运营方一项非独占、全球性、免许可费的许可，仅在为您及获授权用户"
            "运行、保护、排障和改进本服务所合理必要的范围内托管、复制、转换、传输和展示。",
            "您保证有权提交并处理用户内容。请勿上传机密、个人信息、超出合法权利的付费或"
            "版权材料、恶意软件及非法取得的数据；不得删除或歪曲来源网址、引用、许可证、"
            "时间戳和出处。",
        ),
    ),
    LegalSection(
        id="acceptable-use",
        title="7. 可接受使用与禁止行为",
        body=(
            "不得利用本服务违法或侵害第三方权利，或协助欺诈、市场操纵、骚扰、歧视、监控、"
            "窃取凭据、恶意软件和武器伤害；不得制作欺骗性金融宣传、探查其他用户数据、规避"
            "限流、利用提示注入、套取受保护系统指令或秘密，亦不得干扰服务可用性。",
            "安全研究必须获得授权、保持适度并负责任披露。不得在公开 Issue 中发布漏洞细节、"
            "个人信息、凭据或敏感日志。运营方可移除有害内容，并在安全、审计或法律义务合理"
            "需要时保留有限记录。",
        ),
    ),
    LegalSection(
        id="privacy",
        title="8. 隐私告知与数据处理",
        body=(
            "邮箱地址属于个人信息。本服务为连续性与问责需要保存账户邮箱、密码摘要、邮箱验证"
            "状态、会话、同意记录、"
            "自选经验偏好、审计事件、事件包、情景、实验、导出及 AI 相关对话记录。密码和验证"
            "码不会以明文保存。账户邮箱仅用于账户访问、验证、安全、支持和研究数据归属，不会"
            "被放入发送给 AI 或搜索供应商的提示词。请勿提交敏感内容。",
            "数据用于认证、提供和个性化工作流、执行所请求分析、保持可复现性、防止滥用、"
            "诊断故障和运营服务。仅在所请求功能必要时向基础设施、AI 或搜索供应商披露有限"
            "数据；本服务不保证第三方在您所在国家或地区处理数据。",
            "认证 Cookie 与浏览器存储用于会话安全、语言、主题、临时 API 配置及工作流连续性。"
            "登录用户重新输入当前密码后，可在产品内“账户与隐私”页面导出主数据库当前保存的"
            "账户数据，或请求删除账户。删除会移除活动数据库中的账户所属记录并退出登录；如"
            "技术上无法立即从备份中选择性删除，受加密或访问控制保护的备份副本可能保留到计划"
            "到期。仅在安全、防欺诈或法律义务合理必要时保留有限记录。其他请求应通过运营方"
            "提供的私密渠道提出；切勿在公开仓库 Issue 中提交敏感信息。",
            "反向代理与流量统计日志可能为安全、限流、事件响应和汇总运营而临时处理网络地址、"
            "请求时间、路径、状态、设备或浏览器 User-Agent 等连接元数据。受管理的访问日志"
            "格式会排除或脱敏认证 Cookie、Authorization 头、CSRF Token、会话标识和 API "
            "密钥；运营日志受服务器轮换和访问控制约束。",
        ),
    ),
    LegalSection(
        id="security",
        title="9. 安全、可用性与条款更新",
        body=(
            "本服务采取合理保护措施，但任何网络服务、模型、搜索引擎和存储系统都无法保证绝对"
            "安全、连续或无误。维护、供应商故障、模型变化、配额、攻击或实验性软件均可能延迟、"
            "改变或移除功能；您应自行保存工作所需的导出。",
            "运营方可调整服务，并可在继续使用登录功能前要求接受新版本。重大变更将显著展示；"
            "只有完成明确同意才记录为接受，沉默本身不构成同意。",
        ),
    ),
    LegalSection(
        id="intellectual-property",
        title="10. 项目软件与知识产权",
        body=(
            "项目软件仅依据仓库根目录 LICENSE 中标明的许可证提供。源代码公开可见并不授予"
            "许可证之外的权利；产品名称、标识、托管数据、第三方模型及第三方内容可能受其他"
            "权利约束。",
            "除前述用户内容许可外，本条款不转移所有权。运营方可在不支付报酬的情况下使用反馈，"
            "但不会故意公开通过获授权私密渠道明确标注的机密信息。",
        ),
    ),
    LegalSection(
        id="disclaimers",
        title="11. 免责声明与风险分配",
        body=(
            "在适用法律允许的最大范围内，本服务按“现状”和“可用”提供，不保证准确性、特定"
            "用途适用性、适销性、不侵权、可用性或结果。本条款不排除依法不得排除的保证或权利。",
            "在适用法律允许的最大范围内，运营方不对间接、附带、特殊、示范性、后果性或惩罚性"
            "损害，以及利润、交易、数据损失或业务中断承担责任；依法不得排除的责任仅在法律"
            "允许范围内受到限制。",
        ),
    ),
    LegalSection(
        id="indemnity-termination",
        title="12. 补偿、暂停、终止与一般条款",
        body=(
            "在法律允许范围内，因您的非法用户内容、违反本条款、滥用第三方服务或侵害他人权利"
            "引发的第三方主张，您应为运营方抗辩并承担补偿；由运营方自身违法行为造成的部分"
            "不适用该义务。",
            "您可随时停止使用。运营方可因重大违约、安全风险、法律义务或停止服务而暂停或终止"
            "访问。按性质应持续有效的所有权、免责声明、风险分配、审计完整性和已发生义务在"
            "终止后继续有效。",
            "若某条不可执行，应缩减至必要的最小范围，其余条款继续有效；未行使权利不构成放弃。"
            "适用法律在不排除您享有的强制性保护前提下管辖。本条款、页面所示隐私告知及纳入的"
            "通知构成关于本服务的完整约定，另有书面签署协议的除外。",
        ),
    ),
)


def _documentWithoutHash(locale: LegalLocale) -> LegalDocument:
    isChinese = locale == "zh-CN"
    return LegalDocument(
        version=CURRENT_TERMS_VERSION,
        effectiveDate=CURRENT_TERMS_EFFECTIVE_DATE,
        locale=locale,
        title=(
            "EventShock Lab 使用条款与隐私告知"
            if isChinese
            else "EventShock Lab Terms of Use and Privacy Notice"
        ),
        summary=(
            "继续前请完整阅读。您必须年满 18 周岁，理解本服务仅用于研究情景分析，并对 AI "
            "建议、来源和最终提交承担人工复核责任。"
            if isChinese
            else "Read this document before continuing. You must be at least 18, understand "
            "that this is a research scenario tool, and remain responsible for reviewing AI "
            "suggestions, sources, and every final submission."
        ),
        operatorLabel=(
            "EventShock Lab 项目运营方" if isChinese else "EventShock Lab project operators"
        ),
        minimumAge=MINIMUM_ACCOUNT_AGE,
        sections=_ZH_SECTIONS if isChinese else _EN_SECTIONS,
        acceptanceStatements=(
            (
                "我已阅读并同意本版本《使用条款与隐私告知》，并同意以本次勾选和"
                "“同意并继续”操作作为我的电子签名。",
                "我确认已年满 18 周岁，并有权订立本协议。",
                "我理解 AI 和搜索输出必须经过人工审核，且本服务不构成预测或投资建议。",
            )
            if isChinese
            else (
                "I have read and agree to this version of the Terms of Use and Privacy Notice, "
                "and intend these selections and the “Accept and continue” action as my "
                "electronic signature.",
                "I confirm that I am at least 18 years old and legally able to enter "
                "this agreement.",
                "I understand that AI and search output requires human review and is "
                "not a forecast or investment advice.",
            )
        ),
        legalReviewNotice=(
            "本文件是项目生成的版本化电子同意草案与审计记录，不是法律意见，也不保证在任何"
            "司法辖区必然有效或可执行。扩大运营、面向未成年人或处理跨境数据前，必须由熟悉"
            "适用司法辖区的合格法律人士审阅运营主体、联系方式、适用法律、隐私与教育使用"
            "安排。如对自身权利或具体情形有疑问，请咨询合格的专业法律人士。"
            if isChinese
            else "This is a project-generated, versioned consent draft and audit record, not "
            "legal advice or a guarantee of validity or enforceability in any jurisdiction. "
            "Before broader operation, use by minors, or cross-border processing, qualified "
            "counsel familiar with the applicable jurisdictions must review the operator "
            "identity, contact channel, governing law, privacy disclosures, and educational-use "
            "arrangements. Seek qualified professional legal advice about your own rights or "
            "specific circumstances."
        ),
    )


def legalDocument(locale: LegalLocale) -> LegalDocument:
    document = _documentWithoutHash(locale)
    payload = document.model_dump(mode="json", exclude={"documentHash"})
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return document.model_copy(update={"documentHash": digest})


def currentDocumentHashes() -> dict[LegalLocale, str]:
    return {locale: legalDocument(locale).documentHash for locale in ("en", "zh-CN")}


def validateCurrentAcceptance(
    *,
    version: str,
    documentHash: str,
    locale: LegalLocale,
    acceptedTerms: bool,
    confirmedMinimumAge: bool,
    acknowledgedAiBoundary: bool,
) -> LegalDocument:
    document = legalDocument(locale)
    if version != document.version or not secretsEqual(documentHash, document.documentHash):
        raise ValueError("the legal document version changed; reload and review the current terms")
    if not acceptedTerms or not confirmedMinimumAge or not acknowledgedAiBoundary:
        raise ValueError("all required legal acceptance statements must be affirmed")
    return document


def secretsEqual(left: str, right: str) -> bool:
    """固定长度摘要的常量时间比较，避免版本校验形成不必要的时序差异。"""

    return hmac.compare_digest(
        hashlib.sha256(left.encode()).digest(),
        hashlib.sha256(right.encode()).digest(),
    )


def publicLegalPayload(locale: LegalLocale) -> dict[str, Any]:
    return legalDocument(locale).model_dump(mode="json")
