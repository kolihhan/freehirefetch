"""Conservative source-evidence tags, not applicant fit or exclusion rules."""
import re
from collections import Counter

# Preserve unknown and preferred; never turn missing evidence into a rejection.
def match(pattern,text):
    return re.search(pattern,text,re.I)

def tag_role(title, text="", grade="TITLE_ONLY", metadata=None):
    metadata=metadata or {}
    t=str(title or "")
    body=str(text or "")
    # A qualification or employer intro is not evidence of day-to-day AI work.
    duty_heading=re.search(r"(?:岗位职责|工作职责|职位描述|Responsibilities|What you.ll do|Key Responsibilities)\s*[:：/]?",body,re.I)
    if duty_heading:
        duty_tail=body[duty_heading.end():]
        requirements_heading=re.search(r"(?:任职要求|岗位要求|Qualifications|Requirements|What we.re looking for|Minimum Qualifications)\s*[:：/]?",duty_tail,re.I)
        duties=duty_tail[:requirements_heading.start()] if requirements_heading else duty_tail
    else:
        duties=body
    ev=[]
    def note(field,m,origin):
        if m: ev.append({"field":field,"quote":m.group(0)[:180],"origin":origin})
    nontech=match(r"\b(?:sales|account executive|marketing manager|product manager|recruiter|business development|talent acquisition|customer success)\b|销售|产品经理|商务拓展|招聘专员|运营专员|数据运营|市场营销",t)
    research=match(r"\b(?:research(?:er| (?:engineer|assistant|associate|scientist|fellow|officer))|applied scientist)\b|研究员|研究科学家|研究助理|研究工程师|算法研究",t)
    model=match(r"\b(?:LLMs?|NLP|RAG|agentic|AI agents?|generative AI|genAI|machine learning|AI engineer|AI scientist|model evaluation|AI research|ML engineer|deep learning)\b|大模型|智能体|自然语言处理|模型评测|AI(?:应用|算法|研发|工程)|机器学习",t)
    conventional=match(r"\b(?:software engineer|backend|back.end|full.stack|frontend|front.end|mobile|android|iOS|QA|test engineer|devops|data engineer)\b|后端|前端|全栈|客户端|测试开发|软件开发|数据工程|软件工程师|\b(?:developer|programmer|software development engineer|systems engineer|SRE)\b",t)
    domain_other=match(r"\b(?:textile|chemistry|chemical synthesis|materials characterization|photonics|wet lab|knitted fabrics)\b|纺织|材料表征|化学合成",body)
    # Require an action and a concrete AI object; mere company/product names are not enough.
    ai_action=match(r"\b(?:build|develop|implement|design|train|fine.tune|evaluate|optimize|optimise|deploy|integrate|research)\w*\b[^.;。]{0,100}\b(?:LLMs?|language models?|RAG|retrieval.augmented generation|AI agents?|agentic (?:systems?|workflows?)|machine learning (?:models?|algorithms?|systems?)|NLP models?|model evaluation|reward models?)\b|(?:研发|开发|构建|设计|训练|微调|评测|优化|部署)[^。；\n]{0,45}(?:大模型|智能体|模型评测|自然语言处理|检索增强|机器学习模型)",duties)
    research_action=match(r"\b(?:pre.training|post.training|reinforcement learning|fine.tuning|model architecture|reward modeling|model evaluation|benchmark design|training data)\b|预训练|后训练|强化学习|模型结构|模型评测|基准评测|奖励模型",duties)
    title_model=match(r"\b(?:LLM|NLP|RAG|machine learning|AI agent|AI engineer|research scientist|model evaluation)\b|大模型|智能体|模型评测|自然语言",t)
    family="UNKNOWN"
    if nontech: family="NON_TECHNICAL";note("role_family",nontech,"TITLE")
    elif research and (model or ai_action): family="AI_RESEARCH";note("role_family",research,"TITLE")
    elif research: family="OTHER_RESEARCH" if domain_other else "RESEARCH_UNSPECIFIED";note("role_family",research,"TITLE")
    elif conventional and ai_action: family="AI_ENGINEERING";note("role_family",ai_action,grade)
    elif conventional: family="SOFTWARE_ENGINEERING";note("role_family",conventional,"TITLE")
    elif model: family="AI_ENGINEERING";note("role_family",model,"TITLE")
    elif ai_action: family="AI_ENGINEERING";note("role_family",ai_action,grade)
    depth="UNKNOWN"
    if nontech: depth="NOT_CORE_AI"
    elif ai_action:
        depth="MODEL_RESEARCH_OR_EVALUATION" if research_action else "AI_SYSTEM_DEVELOPMENT"
        note("ai_depth",ai_action,grade)
        if research_action: note("ai_depth",research_action,grade)
    elif conventional and (model or match(r"\bAI\b|人工智能",t)): depth="AI_PRODUCT_CONTEXT_ONLY";note("ai_depth",model or match(r"\bAI\b|人工智能",t),"TITLE")
    elif title_model: depth="AI_TITLE_ONLY";note("ai_depth",title_model,"TITLE")
    elif model: depth="AI_TITLE_ONLY";note("ai_depth",model,"TITLE")
    elif research and domain_other: depth="NON_AI_RESEARCH_SIGNAL";note("ai_depth",domain_other,grade)
    # Detect explicit minimum, not arbitrary years in company descriptions.
    exp=[]
    for m in re.finditer(r"\b(\d{1,2})\s*(?:\+|or more)\s*years?\b|\b(?:at least|minimum of|minimum|min\.?)\s*(\d{1,2})\s*(?:\(\d+\)\s*)?years?\b|(?:具备|至少|不少于|最低|要求|拥有|有)\s*(\d{1,2})\s*年(?:及|或)?以上|\b(\d{1,2})\s*年(?:及|或)?以上(?:的)?(?:工作|研发|开发|相关|工程|专业|测试|后端|软件|算法|产品)经验",body,re.I):
        context=body[max(0,m.start()-65):min(len(body),m.end()+80)]
        if match(r"\b(?:preferred|nice to have|bonus|advantage|desirable)\b|优先|加分|更佳",context): continue
        if not match(r"\b(?:experience|professional|engineering|development|research|working|work)\b|经验|研发|开发|工作",context): continue
        n=int(next(g for g in m.groups() if g is not None))
        if n<=30: exp.append(n);note("experience_min_mentions",m,grade)
    # Range lower bound is an explicit minimum mention, not a preferred maximum.
    for m in re.finditer(r"\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*years?\s+(?:of\s+)?(?:relevant\s+|professional\s+|hands.on\s+|work\s+)?experience\b|\bmore than\s+(\d{1,2})\s+years?\s+(?:of\s+)?(?:\w+\s+){0,5}experience\b",body,re.I):
        context=body[max(0,m.start()-65):min(len(body),m.end()+50)]
        if match(r"\b(?:preferred|nice to have|good to have|bonus|desirable)\b|优先|加分",context): continue
        n=int(m.group(1) or m.group(3))
        if n<=30: exp.append(n);note("experience_min_mentions",m,grade)
    rights=match(r"\bonly Singapore Citizens? (?:and|or|/)\s*(?:Singapore )?(?:Permanent Residents?|PRs?)\b|\b(?:employment pass|work visa|visa) sponsorship (?:is )?(?:not available|not provided|not offered)\b|\b(?:must (?:already )?be|should already be|must currently be)\s+based in (?:Singapore|Malaysia|China)\b|仅限(?:新加坡|中国|马来西亚)(?:公民|国籍)",body)
    if rights: note("work_location_or_authorization_restriction",rights,grade)
    em=str(metadata.get("employment_type") or "")+" "+str(metadata.get("recruit_label") or "")
    internship=match(r"\b(?:internship|intern|iXp)\b|实习",t+" "+em)
    # Explicit duration or intern requirement, not reference to internship experience.
    jd_intern=match(r"实习时长|每周\s*(?:[≥>=]|至少)?\s*\d+\s*天[^。；]{0,30}实习|\binternship duration\b|\b(?:internship of|intern for)\s+\d+\s+months?\b",body)
    contract=match(r"\b(?:fixed.term|temporary|contractor|contract position|contract role)\b|劳务派遣|固定期限|短期合同",t+" "+em)
    permanent=match(r"\bpermanent\b|正式|无固定期限",em)
    employment="UNKNOWN"
    if internship or jd_intern: employment="INTERNSHIP";note("employment",internship or jd_intern,"TITLE_OR_METADATA" if internship else grade)
    elif contract: employment="CONTRACT_SIGNAL";note("employment",contract,"TITLE_OR_METADATA")
    elif permanent: employment="PERMANENT_SIGNAL";note("employment",permanent,"METADATA")
    elif match(r"\bfull\s*[- ]?\s*time\b|全职",em): employment="FULL_TIME_UNSPECIFIED_TERM"
    sr=match(r"\b(?:senior|sr\.?|staff|principal|lead|director|head|manager|architect)\b|高级|资深|专家|负责人|架构师|总监",t)
    graduate=match(r"\b(?:graduate|new grad|fresh graduate|junior|entry.level|early career)\b|校招|应届|初级|\d{4}届",t+" "+em)
    seniority="SENIOR_TITLE" if sr else "EARLY_CAREER_TITLE" if graduate else "UNKNOWN"
    note("seniority",sr or graduate,"TITLE_OR_METADATA")
    cohorts=sorted(set(re.findall(r"(?<!\d)(20[2-4]\d)\s*届",t+" "+em)))
    title_phd=match(r"\(\s*Ph\.?\s*D\.?\s*\)|博士岗|博士专场",t)
    phd=match(r"\b(?:Ph\.?\s*D\.?|doctorate|doctoral degree)\s*(?:is\s+)?(?:required|mandatory|essential)\b|\b(?:must (?:have|hold)|required to hold)\s+(?:a\s+)?(?:Ph\.?\s*D\.?|doctorate)\b|(?:须|必须|要求)(?:具备|具有|为)?博士(?:学历|学位|毕业生)|博士毕业生加入|(?:仅限|限)博士|博士及以上",body)
    phd_pref=match(r"\b(?:Ph\.?\s*D\.?|doctorate)\s*(?:is\s+)?(?:preferred|a plus)\b|博士优先",body)
    # Alternatives are not PhD-only. Explicit preferred PhD remains a separate signal.
    if phd and match(r"硕士(?:研究生)?(?:或|及|和|/|、)博士|master.s[^.;]{0,25}(?:or|/)\s*(?:Ph\.?\s*D\.?|doctorate)",body): phd=None
    masters=match(r"硕士(?:研究生)?及以上|硕士以上|硕士学位及以上|\b(?:master.s|master) degree (?:or higher|or above|required)\b",body)
    bachelors=match(r"本科及以上|本科以上|\bbachelor.s degree (?:or higher|or above|required)\b",body)
    degree="UNKNOWN"
    if phd: degree="PHD_REQUIRED_SIGNAL";note("degree",phd,grade)
    elif title_phd: degree="PHD_TITLE_SIGNAL";note("degree",title_phd,"TITLE")
    elif masters: degree="MASTER_MIN_SIGNAL";note("degree",masters,grade)
    elif bachelors: degree="BACHELOR_MIN_SIGNAL";note("degree",bachelors,grade)
    if phd_pref: note("degree_preferred",phd_pref,grade)
    return {"role_family":family,"ai_depth":depth,"seniority":seniority,"degree":degree,
            "phd_preferred_signal":bool(phd_pref),"experience_min_mentions":sorted(set(exp)),
            "employment":employment,"graduation_cohorts":cohorts,"work_location_or_authorization_restriction":bool(rights),"text_evidence_grade":grade,
            "evidence":ev[:14]}
