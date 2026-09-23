"""Phase 1 seed — 분야·시대·학파·기관·사건·2차 출처."""

# (id, label, label_ko, parent)
DOMAINS = [
    ("domain:philosophy", "Philosophy", "철학", None),
    ("domain:metaphysics", "Metaphysics", "형이상학", "domain:philosophy"),
    ("domain:epistemology", "Epistemology", "인식론", "domain:philosophy"),
    ("domain:ethics", "Ethics", "윤리학", "domain:philosophy"),
    ("domain:logic", "Logic", "논리학", "domain:philosophy"),
    ("domain:political-philosophy", "Political Philosophy", "정치철학", "domain:philosophy"),
    ("domain:philosophy-of-science", "Philosophy of Science", "과학철학", "domain:philosophy"),
    ("domain:philosophy-of-language", "Philosophy of Language", "언어철학", "domain:philosophy"),
    ("domain:science", "Science", "과학", None),
    ("domain:physics", "Physics", "물리학", "domain:science"),
    ("domain:astronomy", "Astronomy", "천문학", "domain:science"),
    ("domain:biology", "Biology", "생물학", "domain:science"),
    ("domain:chemistry", "Chemistry", "화학", "domain:science"),
    ("domain:mathematics", "Mathematics", "수학", None),
    ("domain:geometry", "Geometry", "기하학", "domain:mathematics"),
    ("domain:analysis", "Analysis", "해석학", "domain:mathematics"),
    ("domain:algebra", "Algebra", "대수학", "domain:mathematics"),
    ("domain:number-theory", "Number Theory", "정수론", "domain:mathematics"),
    ("domain:mathematical-logic", "Mathematical Logic", "수리논리학", "domain:mathematics"),
    ("domain:economics", "Economics", "경제학", None),
    ("domain:politics", "Politics", "정치", None),
    ("domain:theology", "Theology", "신학", None),
    ("domain:literature", "Literature", "문학", None),
    ("domain:art", "Art", "예술", None),
    ("domain:psychology", "Psychology", "심리학", None),
    ("domain:sociology", "Sociology", "사회학", None),
    ("domain:law", "Law", "법학", None),
]

# (id, label, label_ko, start, end)
ERAS = [
    ("era:classical-greece", "Archaic & Classical Greece", "고대 그리스", -800, -323),
    ("era:hellenistic", "Hellenistic Age", "헬레니즘", -323, -31),
    ("era:roman-late-antiquity", "Roman Empire & Late Antiquity", "로마·고대 후기", -31, 600),
    ("era:medieval", "Middle Ages", "중세", 600, 1400),
    ("era:renaissance", "Renaissance & Reformation", "르네상스·종교개혁", 1400, 1600),
    ("era:early-modern", "Early Modern / Scientific Revolution", "근대 초·과학혁명", 1600, 1700),
    ("era:enlightenment", "Enlightenment", "계몽주의", 1700, 1800),
    ("era:nineteenth-century", "19th Century (Industrial Age)", "19세기·산업혁명", 1800, 1900),
    ("era:twentieth-century", "20th Century", "20세기", 1900, 2000),
    ("era:contemporary", "Contemporary", "현대", 2000, 2100),
]

# (id, type, label, label_ko, start, end, description)
SCHOOLS = [
    ("school:platonism", "School", "Platonism", "플라톤주의", -387, None, "이데아의 실재성을 중심으로 한 전통"),
    ("school:aristotelianism", "School", "Aristotelianism", "아리스토텔레스주의", -335, None, "형상·질료, 목적론, 덕 윤리의 전통"),
    ("school:epicureanism", "School", "Epicureanism", "에피쿠로스학파", -307, None, "원자론과 평정(ataraxia)의 윤리"),
    ("school:stoicism", "School", "Stoicism", "스토아학파", -300, None, "로고스·자연에 따른 삶·내면의 자유"),
    ("school:scholasticism", "School", "Scholasticism", "스콜라 철학", 1100, 1500, "신앙과 이성의 조화를 추구한 중세 대학의 철학"),
    ("school:social-contract", "Movement", "Social Contract Tradition", "사회계약론 전통", 1651, None, "정치적 정당성을 합의에서 찾는 전통"),
    ("school:continental-rationalism", "School", "Continental Rationalism", "대륙 합리론", 1637, 1716, "이성과 본유관념을 지식의 원천으로 보는 입장"),
    ("school:british-empiricism", "School", "British Empiricism", "영국 경험론", 1689, 1776, "경험을 지식의 원천으로 보는 입장"),
    ("school:german-idealism", "School", "German Idealism", "독일 관념론", 1781, 1831, "칸트 이후 주체·정신·자유를 중심으로 한 체계 철학"),
    ("school:existentialism", "Movement", "Existentialism", "실존주의", 1843, None, "실존·자유·책임·부조리를 중심으로 한 사조"),
    ("school:phenomenology", "School", "Phenomenology", "현상학", 1900, None, "의식에 나타나는 그대로의 사태를 기술"),
    ("school:analytic-philosophy", "Movement", "Analytic Philosophy", "분석철학", 1900, None, "논리·언어 분석을 통한 철학"),
    ("school:marxism", "School", "Marxism", "마르크스주의", 1848, None, "역사유물론과 자본주의 비판"),
    ("school:classical-economics", "School", "Classical Political Economy", "고전파 정치경제학", 1776, 1870, "노동가치론과 시장의 자기조정"),
    ("school:keynesianism", "School", "Keynesian Economics", "케인스 경제학", 1936, None, "유효수요와 거시 안정화 정책"),
    ("school:austrian-school", "School", "Austrian School", "오스트리아학파", 1871, None, "주관적 가치·시장 과정·자생적 질서"),
    ("school:critical-rationalism", "School", "Critical Rationalism", "비판적 합리주의", 1934, None, "추측과 논박, 반증주의"),
    ("school:liberalism", "Movement", "Liberalism", "자유주의", 1689, None, "개인의 자유와 권리를 정치의 중심에 두는 사조"),
    ("school:enlightenment", "Movement", "Enlightenment", "계몽주의", 1680, 1800, "이성의 공적 사용과 자율"),
    ("school:natural-law-tradition", "Movement", "Natural Law Tradition", "자연법 전통", -300, None, "이성으로 알 수 있는 보편적 도덕 질서"),
    ("school:utilitarianism", "School", "Utilitarianism", "공리주의", 1789, None, "최대 다수의 최대 행복"),
]

# (id, label, label_ko, founded, description)
INSTITUTIONS = [
    ("inst:academy", "Plato's Academy", "아카데메이아", -387, "플라톤이 아테네에 세운 학원"),
    ("inst:lyceum", "Lyceum", "뤼케이온", -335, "아리스토텔레스의 학원"),
    ("inst:university-of-paris", "University of Paris", "파리 대학", 1150, "스콜라 철학의 중심"),
    ("inst:oxford", "University of Oxford", "옥스퍼드 대학", 1096, ""),
    ("inst:cambridge", "University of Cambridge", "케임브리지 대학", 1209, ""),
    ("inst:konigsberg", "University of Königsberg", "쾨니히스베르크 대학", 1544, ""),
    ("inst:berlin", "University of Berlin", "베를린 대학", 1810, ""),
    ("inst:freiburg", "University of Freiburg", "프라이부르크 대학", 1457, ""),
    ("inst:lse", "London School of Economics", "런던정경대", 1895, ""),
    ("inst:harvard", "Harvard University", "하버드 대학", 1636, ""),
]

# (id, label, label_ko, start, end, description)
EVENTS = [
    ("event:trial-of-socrates", "Trial and Death of Socrates", "소크라테스의 재판과 죽음", -399, -399, ""),
    ("event:sack-of-rome", "Sack of Rome (410)", "로마 약탈", 410, 410, "서고트족의 로마 약탈 — 『신국론』 집필의 계기"),
    ("event:reformation", "Protestant Reformation", "종교개혁", 1517, 1648, ""),
    ("event:scientific-revolution", "Scientific Revolution", "과학혁명", 1543, 1687, "코페르니쿠스에서 뉴턴까지"),
    ("event:english-civil-war", "English Civil War", "영국 내전", 1642, 1651, ""),
    ("event:glorious-revolution", "Glorious Revolution", "명예혁명", 1688, 1689, ""),
    ("event:industrial-revolution", "Industrial Revolution", "산업혁명", 1760, 1840, ""),
    ("event:american-independence", "American Declaration of Independence", "미국 독립선언", 1776, 1776, ""),
    ("event:french-revolution", "French Revolution", "프랑스 혁명", 1789, 1799, ""),
    ("event:revolutions-1848", "Revolutions of 1848", "1848년 혁명", 1848, 1849, ""),
    ("event:world-war-1", "First World War", "제1차 세계대전", 1914, 1918, ""),
    ("event:great-depression", "Great Depression", "대공황", 1929, 1939, ""),
    ("event:world-war-2", "Second World War", "제2차 세계대전", 1939, 1945, ""),
]

# 2차 출처 (id, label, label_ko, tier, description)
SOURCES = [
    ("source:diogenes-laertius", "Diogenes Laertius, Lives of Eminent Philosophers (3rd c.)",
     "디오게네스 라에르티오스, 『유명한 철학자들의 생애』", 2, "고대 전기 — 사제 관계에 대한 전승 기록"),
    ("source:copleston", "F. Copleston, A History of Philosophy (1946–1975)", "코플스턴, 『서양철학사』", 3, ""),
    ("source:kuehn-kant", "M. Kuehn, Kant: A Biography (2001)", "퀸, 『칸트 전기』", 3, ""),
    ("source:strauss-nrh", "L. Strauss, Natural Right and History (1953)", "슈트라우스, 『자연권과 역사』", 3, ""),
    ("source:schumpeter-hea", "J. A. Schumpeter, History of Economic Analysis (1954)", "슘페터, 『경제분석의 역사』", 3, ""),
    ("source:monk-wittgenstein", "R. Monk, Ludwig Wittgenstein: The Duty of Genius (1990)", "몽크, 『비트겐슈타인 평전』", 3, ""),
    ("source:aronson-camus-sartre", "R. Aronson, Camus and Sartre (2004)", "애런슨, 『카뮈와 사르트르』", 3, ""),
    ("source:kaufmann-nietzsche", "W. Kaufmann, Nietzsche: Philosopher, Psychologist, Antichrist (1950)",
     "카우프만, 『니체』", 3, ""),
    ("source:nadler-spinoza", "S. Nadler, Spinoza: A Life (1999)", "내들러, 『스피노자 평전』", 3, ""),
    ("source:westfall-newton", "R. S. Westfall, Never at Rest: A Biography of Isaac Newton (1980)",
     "웨스트폴, 『뉴턴 평전』", 3, ""),
    ("source:sep", "Stanford Encyclopedia of Philosophy (relevant entries)", "스탠퍼드 철학 백과사전", 4,
     "학술 백과사전 — 검토자가 구체적 항목을 지정해야 함"),
]
