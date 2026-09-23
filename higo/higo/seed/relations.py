"""Phase 1 seed — 증거가 붙은 관계 (영향·계승·비판·유사성·맥락).

형식: rel(source, predicate, target, status, evidence, epistemic, origin, note)
evidence 항목: (출처, tier, locator, 해석, stance)
  - 출처가 'work:' 또는 'source:' 로 시작하면 해당 엔티티를 가리킨다.
  - 그 밖의 문자열은 자유 서지 표기(citation)다.

주의: 이 데이터는 온톨로지 작동 검증용 초기 큐레이션이다. 특히 Tier 3~4 증거와
'disputed' 관계는 전문 연구자의 검토가 필요하며, AI 기원 가설(origin='ai')은
의도적으로 검토 큐에 넣어 둔 것이다.
"""


def rel(source, predicate, target, status="direct", evidence=(), epistemic="accepted", origin="seed", note=""):
    return dict(source=source, predicate=predicate, target=target, status=status, evidence=list(evidence),
                epistemic=epistemic, origin=origin, note=note)


def ev(src, tier, locator="", interp="", stance="supports"):
    return (src, tier, locator, interp, stance)


RELATIONS = [
    # ================================================================ 고대
    rel("person:plato", "student_of", "person:socrates", evidence=[
        ev("work:apology", 1, "34a, 38b", "플라톤이 재판정에 있었다고 스스로 기록"),
        ev("source:diogenes-laertius", 2, "III.6")]),
    rel("person:socrates", "influenced", "person:plato", evidence=[
        ev("work:apology", 1, "", "초기 대화편 전체가 소크라테스의 문답을 재현")]),
    rel("person:aristotle", "student_of", "person:plato", evidence=[
        ev("source:diogenes-laertius", 2, "V.1–2", "20년간 아카데메이아에서 수학")]),
    rel("person:plato", "influenced", "person:aristotle", evidence=[
        ev("work:metaphysics", 1, "A.6 987a–988a", "플라톤 철학의 기원과 내용을 정리")]),
    rel("person:aristotle", "criticized", "concept:forms", evidence=[
        ev("work:metaphysics", 1, "A.9 990b–991b; M–N", "분리된 이데아에 대한 체계적 반론")]),
    rel("person:aristotle", "criticized", "work:republic", evidence=[
        ev("work:politics", 1, "II.1–5", "처자·재산 공유론 비판")]),
    rel("person:aristotle", "modified", "concept:forms", evidence=[
        ev("work:metaphysics", 1, "Z", "형상을 개별 실체 안의 원리로 재배치")], note="이데아 → 내재적 형상"),
    rel("concept:forms", "transformed_into", "concept:hylomorphism", evidence=[
        ev("work:metaphysics", 1, "Z–H", "분리된 형상이 질료 안의 형상으로 변형"),
        ev("source:copleston", 3, "Vol. I")]),
    rel("person:aristotle", "defines", "concept:hylomorphism"),
    rel("person:aristotle", "defines", "concept:four-causes"),
    rel("person:aristotle", "defines", "concept:teleology"),
    rel("person:aristotle", "defines", "concept:eudaimonia"),
    rel("person:aristotle", "defines", "concept:just-exchange"),
    rel("person:plato", "defines", "concept:forms"),
    rel("person:plato", "defines", "concept:anamnesis"),
    rel("person:plato", "defines", "concept:philosopher-king"),
    rel("person:epicurus", "defines", "concept:ataraxia"),
    rel("person:epictetus", "defines", "concept:inner-freedom"),
    rel("person:socrates", "defines", "concept:socratic-method"),
    rel("work:apology", "contextualized_by", "event:trial-of-socrates"),

    # ======================================================= 고대 후기·중세
    rel("person:plato", "influenced", "person:augustine", status="indirect", evidence=[
        ev("work:confessions", 1, "VII.9.13–VII.10.16", "'플라톤주의자들의 책'(신플라톤주의 라틴어 번역)을 통해 접함"),
        ev("source:copleston", 3, "Vol. II", "플로티노스를 매개로 한 간접 수용")]),
    rel("person:augustine", "reinterpreted", "concept:forms", status="indirect", evidence=[
        ev("source:copleston", 3, "Vol. II", "이데아를 신의 정신 안의 범형으로 재해석")]),
    rel("work:city-of-god", "contextualized_by", "event:sack-of-rome", evidence=[
        ev("work:city-of-god", 1, "I, preface", "로마 약탈 이후 기독교에 대한 비난에 답하기 위해 집필")]),
    rel("person:augustine", "defines", "concept:two-cities"),
    rel("person:aristotle", "influenced", "person:aquinas", evidence=[
        ev("work:summa-theologiae", 1, "passim", "아리스토텔레스를 '철학자(Philosophus)'로 인용"),
        ev("source:copleston", 3, "Vol. II")]),
    rel("person:augustine", "influenced", "person:aquinas", evidence=[
        ev("work:summa-theologiae", 1, "passim", "아우구스티누스를 가장 많이 인용한 교부 중 하나로 사용")]),
    rel("person:aquinas", "adopted", "concept:hylomorphism", evidence=[
        ev("work:summa-theologiae", 1, "I q.76 a.1", "영혼은 신체의 형상")]),
    rel("person:aquinas", "reinterpreted", "concept:teleology", evidence=[
        ev("work:summa-theologiae", 1, "I q.2 a.3 (fifth way); I-II q.94 a.2", "자연의 목적 지향성을 신의 섭리와 자연법에 통합")]),
    rel("person:aquinas", "adopted", "concept:just-exchange", evidence=[
        ev("work:summa-theologiae", 1, "II-II q.61, q.77", "아리스토텔레스 『니코마코스 윤리학』 V권의 교환 정의를 인용"),
        ev("source:schumpeter-hea", 3, "Part II ch. 2", "스콜라 경제사상의 원천으로서의 아리스토텔레스")]),
    rel("concept:just-exchange", "transformed_into", "concept:just-price", evidence=[
        ev("source:schumpeter-hea", 3, "Part II ch. 2")]),
    rel("person:aquinas", "adopted", "concept:private-property", evidence=[
        ev("work:summa-theologiae", 1, "II-II q.66 a.2", "아리스토텔레스 『정치학』 II권의 논거를 원용")]),
    rel("person:aquinas", "defines", "concept:natural-law"),
    rel("person:aquinas", "defines", "concept:faith-and-reason"),
    rel("school:scholasticism", "defines", "concept:faith-and-reason"),

    # ============================================== 자연법 → 미국 독립 사슬
    rel("person:aquinas", "influenced", "person:hooker", evidence=[
        ev("work:laws-ecclesiastical-polity", 1, "Book I", "법의 위계(영원법·자연법·인정법)를 토마스주의 틀로 전개"),
        ev("source:copleston", 3, "Vol. III")]),
    rel("person:hooker", "influenced", "person:locke", evidence=[
        ev("work:two-treatises", 1, "II §§5, 15, 61", "'현명한 후커(the judicious Hooker)'를 반복 인용")]),
    rel("concept:natural-law", "transformed_into", "concept:natural-rights", status="indirect", evidence=[
        ev("source:strauss-nrh", 3, "ch. V", "고전적 자연법에서 근대적 자연권으로의 전환"),
        ev("work:two-treatises", 1, "II §6", "자연법이 생명·자유·소유의 권리로 표현됨")]),
    rel("person:locke", "influenced", "person:jefferson", evidence=[
        ev("work:letter-to-henry-lee", 1, "8 May 1825", "선언서의 권위가 기댄 원천으로 로크를 명시"),
        ev("work:declaration-of-independence", 1, "Preamble", "생명·자유·행복 추구의 권리")]),
    rel("person:aristotle", "influenced", "person:jefferson", status="indirect", evidence=[
        ev("work:letter-to-henry-lee", 1, "8 May 1825",
           "아리스토텔레스·키케로·로크·시드니를 '당대의 조화된 정서'의 원천으로 언급 — 직접 차용이 아니라 공유된 공론의 배경")],
        note="간접 영향: 자연법 전통을 매개로 한 연결"),
    rel("work:declaration-of-independence", "contextualized_by", "event:american-independence"),
    rel("person:jefferson", "adopted", "concept:natural-rights", evidence=[
        ev("work:declaration-of-independence", 1, "Preamble")]),

    # ========================================================= 근대 정치
    rel("work:laws-ecclesiastical-polity", "contextualized_by", "event:reformation", evidence=[
        ev("source:copleston", 3, "Vol. III", "엘리자베스 시대 국교회 체제를 청교도 비판에 맞서 옹호")]),
    rel("work:leviathan", "contextualized_by", "event:english-civil-war", evidence=[
        ev("source:copleston", 3, "Vol. V")]),
    rel("work:two-treatises", "contextualized_by", "event:glorious-revolution", evidence=[
        ev("source:copleston", 3, "Vol. V")]),
    rel("person:hobbes", "defines", "concept:state-of-nature"),
    rel("person:hobbes", "defines", "concept:social-contract-concept"),
    rel("person:hobbes", "influenced", "person:locke", status="disputed", epistemic="contested", evidence=[
        ev("source:strauss-nrh", 3, "ch. V B", "로크의 자연법 교설은 겉보기와 달리 홉스에 가깝다는 해석"),
        ev("work:two-treatises", 1, "I–II", "『통치론』의 명시적 논적은 홉스가 아니라 필머이며, 홉스를 이름으로 논박하지 않음",
           "contradicts")], note="학계 논쟁 중인 영향 관계"),
    rel("person:rousseau", "criticized", "person:hobbes", evidence=[
        ev("work:discourse-inequality", 1, "Part I", "홉스가 사회적 정념을 자연인에게 투사했다고 비판")]),
    rel("person:rousseau", "responds_to", "person:locke", evidence=[
        ev("work:discourse-inequality", 1, "Part I & notes", "로크의 자연상태·소유론을 검토")]),
    rel("person:rousseau", "defines", "concept:general-will"),
    rel("person:rousseau", "modified", "concept:social-contract-concept", evidence=[
        ev("work:social-contract", 1, "I.6", "각자가 전체에 자신을 양도하는 결합 형식")]),
    rel("work:social-contract", "influenced", "event:french-revolution", status="indirect", evidence=[
        ev("source:copleston", 3, "Vol. VI", "혁명기 지도자들의 루소 수용")]),
    rel("person:machiavelli", "influenced", "person:spinoza", evidence=[
        ev("Spinoza, Political Treatise (1677)", 1, "V.7", "'가장 예리한 마키아벨리'로 칭하며 논의")]),
    rel("person:machiavelli", "defines", "concept:political-realism"),
    rel("person:machiavelli", "influenced", "person:hobbes", status="inferred", epistemic="hypothesis", origin="ai",
        evidence=[ev("HIGO discovery engine (seed example)", 6, "",
                     "두 사람 모두 정치를 도덕적 이상이 아닌 실제 권력 관계로 분석 — 유사성에서 추론된 가설")],
        note="검토 필요: 유사성만으로 영향을 주장할 수 없음"),

    # ======================================================= 합리론 계열
    rel("person:hobbes", "criticized", "person:descartes", evidence=[
        ev("work:meditations", 1, "Third Objections and Replies (1641)", "『성찰』에 대한 셋째 반론의 저자")]),
    rel("person:descartes", "influenced", "person:spinoza", evidence=[
        ev("work:principles-cartesian", 1, "", "데카르트 『철학의 원리』를 기하학적 방식으로 재구성")]),
    rel("person:spinoza", "criticized", "concept:mind-body-dualism", evidence=[
        ev("work:ethics-spinoza", 1, "V preface", "데카르트의 송과선 이론을 비판")]),
    rel("person:spinoza", "rejected", "concept:free-will", evidence=[
        ev("work:ethics-spinoza", 1, "II prop. 48; I appendix")]),
    rel("person:spinoza", "rejected", "concept:teleology", evidence=[
        ev("work:ethics-spinoza", 1, "I appendix")]),
    rel("person:spinoza", "defines", "concept:substance-monism"),
    rel("person:spinoza", "defines", "concept:freedom-as-necessity"),
    rel("person:descartes", "defines", "concept:cogito"),
    rel("person:descartes", "defines", "concept:mind-body-dualism"),
    rel("person:descartes", "defines", "concept:analytic-geometry"),
    rel("person:leibniz", "responds_to", "person:spinoza", evidence=[
        ev("source:nadler-spinoza", 3, "ch. 12", "1676년 헤이그 방문과 『에티카』 원고 열람")]),
    rel("person:leibniz", "criticized", "person:locke", evidence=[
        ev("work:new-essays", 1, "Preface & Book I", "로크 『인간지성론』에 대한 대화체 반론")]),
    rel("person:leibniz", "criticized", "concept:tabula-rasa", evidence=[
        ev("work:new-essays", 1, "Preface", "결이 있는 대리석의 비유")]),
    rel("concept:anamnesis", "transformed_into", "concept:innate-ideas", evidence=[
        ev("work:discourse-on-metaphysics", 1, "§26", "라이프니츠가 플라톤의 상기설을 본유관념론으로 재해석"),
        ev("work:new-essays", 1, "Preface")]),
    rel("person:plato", "influenced", "person:leibniz", evidence=[
        ev("work:discourse-on-metaphysics", 1, "§26", "상기설을 명시적으로 옹호")]),
    rel("person:leibniz", "criticized", "person:newton", evidence=[
        ev("work:leibniz-clarke", 1, "Letters 2–5", "뉴턴 측 클라크와 절대공간·신의 개입을 두고 논쟁")]),
    rel("person:leibniz", "criticized", "concept:absolute-space", evidence=[
        ev("work:leibniz-clarke", 1, "3rd letter §§4–6")]),
    rel("person:leibniz", "defines", "concept:monad"),
    rel("person:leibniz", "defines", "concept:relational-space"),
    rel("person:leibniz", "defines", "concept:calculus"),
    rel("person:newton", "defines", "concept:calculus"),
    rel("person:augustine", "influenced", "person:descartes", status="disputed", epistemic="contested", evidence=[
        ev("work:meditations", 1, "Fourth Objections (Arnauld)", "아르노가 코기토와 아우구스티누스 『자유의지론』 II.3의 유사성을 지적"),
        ev("Descartes, letter to Colvius, 14 Nov. 1640", 1, "AT III 247–248",
           "아우구스티누스와의 일치는 반갑지만 자신은 전혀 다른 목적(정신의 비물질성 증명)으로 사용한다고 답함", "contradicts")],
        note="유사성은 확실하나 영향은 논쟁 중"),

    # =================================================== 과학혁명 → 철학
    rel("person:descartes", "influenced", "person:newton", evidence=[
        ev("source:westfall-newton", 3, "ch. 4", "학생 시절 데카르트 『기하학』(판 스호텐 판)을 독학")]),
    rel("person:newton", "adopted", "concept:analytic-geometry", evidence=[
        ev("source:westfall-newton", 3, "ch. 4")]),
    rel("person:newton", "defines", "concept:universal-gravitation"),
    rel("person:newton", "defines", "concept:absolute-space"),
    rel("person:newton", "defines", "concept:experimental-method"),
    rel("work:principia", "contextualized_by", "event:scientific-revolution"),
    rel("work:meditations", "contextualized_by", "event:scientific-revolution"),
    rel("person:newton", "influenced", "person:hume", evidence=[
        ev("work:treatise-human-nature", 1, "title page & Introduction",
           "부제 '도덕적 주제에 실험적 추론 방법을 도입하려는 시도'")]),
    rel("person:hume", "adopted", "concept:experimental-method", evidence=[
        ev("work:treatise-human-nature", 1, "Introduction")]),
    rel("person:locke", "influenced", "person:hume", evidence=[
        ev("work:treatise-human-nature", 1, "Introduction", "인간학을 새 토대 위에 세운 선구자로 로크를 언급")]),
    rel("person:newton", "influenced", "person:kant", evidence=[
        ev("work:universal-natural-history", 1, "Preface", "뉴턴 역학 원리로 천체의 기원을 설명")]),
    rel("person:newton", "influenced", "person:einstein", evidence=[
        ev("work:autobiographical-notes", 1, "", "'뉴턴이여, 용서하시라' — 뉴턴 개념의 극복을 서술")]),
    rel("person:einstein", "rejected", "concept:absolute-space", evidence=[
        ev("work:special-relativity", 1, "Introduction", "절대 정지 공간과 에테르가 불필요하다고 논증")]),
    rel("person:einstein", "defines", "concept:relativity"),

    # ====================================================== 계몽 → 칸트
    rel("person:hume", "influenced", "person:kant", evidence=[
        ev("work:prolegomena", 1, "Preface 4:260", "흄이 '독단의 잠'을 깨웠다고 증언"),
        ev("source:kuehn-kant", 3, "")]),
    rel("person:kant", "responds_to", "concept:problem-of-induction", evidence=[
        ev("work:prolegomena", 1, "Preface", "흄의 인과 문제에 대한 응답으로서 비판철학")]),
    rel("person:rousseau", "influenced", "person:kant", evidence=[
        ev("work:kant-remarks", 1, "AA 20:44", "'루소가 나를 바로잡았다' — 인간 존중을 배웠다는 메모"),
        ev("source:kuehn-kant", 3, "ch. 4")]),
    rel("person:plato", "influenced", "person:kant", status="indirect", evidence=[
        ev("work:critique-of-pure-reason", 1, "A313–320/B370–377", "플라톤의 '이데아'를 이성 개념으로 재해석"),
        ev("source:sep", 4, "", "칸트의 플라톤 이해는 주로 2차 문헌(브루커 등)을 통한 것이라는 통설 — 검토자가 구체 문헌 지정 필요")],
        note="Plato ──influenced──→ Kant 와 Plato ──similar_to──→ Kant 는 다른 주장이다"),
    rel("person:plato", "similar_to", "person:kant", status="inferred", evidence=[
        ev("source:copleston", 3, "Vol. VI", "현상/물자체 구분과 감각계/예지계 구분의 구조적 유사성")],
        note="구조적 유사성 — 영향 관계와 별개로 기록"),
    rel("person:kant", "defines", "concept:synthetic-a-priori"),
    rel("person:kant", "defines", "concept:transcendental-idealism"),
    rel("person:kant", "defines", "concept:categorical-imperative"),
    rel("person:kant", "defines", "concept:enlightenment-concept"),
    rel("concept:moral-freedom", "transformed_into", "concept:categorical-imperative", status="indirect", evidence=[
        ev("source:kuehn-kant", 3, "", "루소의 도덕적 자유(자기 입법)가 칸트의 자율 개념으로 이어짐")]),
    rel("person:kant", "modified", "concept:moral-freedom", evidence=[
        ev("work:groundwork", 1, "4:440–441", "의지의 자율을 도덕의 최고 원리로")]),
    rel("person:hume", "influenced", "person:smith", evidence=[
        ev("work:theory-moral-sentiments", 1, "IV.i.2", "'재치 있고 유쾌한 저자'로 흄의 효용론을 논의")]),
    rel("person:hume", "defines", "concept:problem-of-induction"),
    rel("person:hume", "defines", "concept:is-ought"),

    # ================================================== 독일 관념론 이후
    rel("person:kant", "influenced", "person:hegel", evidence=[
        ev("work:faith-and-knowledge", 1, "A. Kantian Philosophy", "칸트 철학을 '반성철학'으로 분석")]),
    rel("person:hegel", "criticized", "person:kant", evidence=[
        ev("work:faith-and-knowledge", 1, "A", "물자체와 유한한 지성의 한계를 비판")]),
    rel("person:spinoza", "influenced", "person:hegel", evidence=[
        ev("Hegel, Lectures on the History of Philosophy, vol. III", 1, "on Spinoza",
           "'스피노자주의는 모든 철학함의 본질적 시작'")]),
    rel("person:hegel", "adopted", "concept:freedom-as-necessity", status="indirect", evidence=[
        ev("work:lectures-philosophy-of-history", 1, "Introduction")]),
    rel("person:hegel", "defines", "concept:dialectic"),
    rel("person:hegel", "defines", "concept:absolute-spirit"),
    rel("person:kant", "influenced", "person:schopenhauer", evidence=[
        ev("work:world-as-will", 1, "Appendix: Critique of the Kantian Philosophy")]),
    rel("person:schopenhauer", "criticized", "person:hegel", evidence=[
        ev("work:world-as-will", 1, "Preface to 2nd ed. (1844)", "헤겔을 사이비 철학자로 비난")]),
    rel("person:schopenhauer", "defines", "concept:will-schopenhauer"),
    rel("person:hegel", "influenced", "person:marx", evidence=[
        ev("work:capital", 1, "Afterword to 2nd German ed. (1873)", "스스로 '저 위대한 사상가의 제자'라고 밝힘")]),
    rel("person:marx", "criticized", "person:hegel", evidence=[
        ev("work:capital", 1, "Afterword to 2nd German ed. (1873)", "머리로 선 변증법을 바로 세워야 한다")]),
    rel("person:marx", "modified", "concept:dialectic", evidence=[
        ev("work:capital", 1, "Afterword to 2nd German ed.")]),
    rel("concept:dialectic", "transformed_into", "concept:historical-materialism", evidence=[
        ev("work:capital", 1, "Afterword to 2nd German ed."),
        ev("work:theses-on-feuerbach", 1, "I, XI")]),
    rel("person:epicurus", "influenced", "person:marx", evidence=[
        ev("work:marx-dissertation", 1, "", "박사논문 주제")]),
    rel("person:marx", "defines", "concept:historical-materialism"),
    rel("person:marx", "defines", "concept:surplus-value"),
    rel("person:marx", "defines", "concept:alienation"),
    rel("person:marx", "rejected", "concept:private-property", evidence=[
        ev("work:communist-manifesto", 1, "Section II")]),
    rel("person:engels", "adopted", "concept:freedom-as-necessity", evidence=[
        ev("F. Engels, Anti-Dühring (1878)", 1, "Part I ch. XI", "'자유는 필연성의 인식' — 헤겔을 인용")]),
    rel("person:marx", "student_of", "person:hegel", status="indirect", epistemic="rejected", evidence=[
        ev("source:copleston", 3, "Vol. VII", "마르크스는 헤겔 사후(1831) 베를린 대학에 입학 — 직접 사사 불가", "contradicts")],
        note="기각된 관계의 예: 제자 관계가 아니라 청년헤겔학파를 통한 수용"),
    rel("work:communist-manifesto", "contextualized_by", "event:revolutions-1848"),
    rel("work:capital", "contextualized_by", "event:industrial-revolution"),
    rel("person:marx", "defines", "concept:ideology-critique"),
    rel("person:nietzsche", "defines", "concept:ideology-critique"),
    rel("person:marx", "criticized", "concept:faith-and-reason", status="indirect", evidence=[
        ev("work:critique-hegel-right-intro", 1, "")]),
    rel("person:kierkegaard", "criticized", "person:hegel", evidence=[
        ev("work:concluding-postscript", 1, "Part II", "체계는 실존하는 개인을 설명하지 못한다")]),
    rel("person:kierkegaard", "defines", "concept:truth-as-subjectivity"),
    rel("person:kierkegaard", "defines", "concept:leap-of-faith"),

    # ============================================================ 경제학
    rel("person:smith", "defines", "concept:invisible-hand"),
    rel("person:smith", "defines", "concept:division-of-labor"),
    rel("person:smith", "influenced", "person:ricardo", evidence=[
        ev("work:principles-political-economy", 1, "Preface; ch. 1", "스미스의 가치론을 비판적으로 계승")]),
    rel("person:ricardo", "extended", "concept:labor-theory-of-value", evidence=[
        ev("work:principles-political-economy", 1, "ch. 1")]),
    rel("person:ricardo", "defines", "concept:comparative-advantage"),
    rel("person:ricardo", "influenced", "person:marx", evidence=[
        ev("work:capital", 1, "Afterword to 2nd German ed.", "리카도를 고전파 정치경제학의 마지막 위대한 대표자로 평가")]),
    rel("person:smith", "influenced", "person:marx", evidence=[
        ev("work:capital", 1, "ch. 14", "매뉴팩처 분업 논의에서 스미스를 광범위하게 인용")]),
    rel("person:marx", "modified", "concept:labor-theory-of-value", evidence=[
        ev("work:capital", 1, "chs. 1, 6–7", "노동과 노동력의 구분")]),
    rel("concept:labor-theory-of-value", "transformed_into", "concept:surplus-value", evidence=[
        ev("work:capital", 1, "chs. 6–7")]),
    rel("person:marx", "criticized", "concept:division-of-labor", evidence=[
        ev("work:capital", 1, "ch. 14 §5", "분업이 노동자를 불구로 만든다 — 플라톤의 분업론도 언급")]),
    rel("concept:labor-theory-of-property", "transformed_into", "concept:labor-theory-of-value", status="inferred",
        epistemic="hypothesis", origin="ai", evidence=[
            ev("HIGO discovery engine (seed example)", 6, "",
               "로크 §27의 노동-소유 논변과 스미스·리카도의 노동가치론의 개념적 유사성에서 추론")],
        note="검토 필요: 소유의 정당화와 가치의 측정은 다른 문제일 수 있음"),
    rel("person:plato", "influenced", "person:smith", status="inferred", epistemic="hypothesis", origin="ai", evidence=[
        ev("HIGO discovery engine (seed example)", 6, "", "『국가』 II권과 『국부론』 I권의 분업 논변 유사성에서 추론")],
        note="유사성 ≠ 영향: 원전 증거가 없으면 기각되어야 할 가설의 예"),
    rel("person:keynes", "criticized", "person:ricardo", evidence=[
        ev("work:general-theory", 1, "ch. 3", "리카도의 승리는 '종교재판이 스페인을 정복하듯' 완전했다며 고전파를 비판")]),
    rel("person:keynes", "criticized", "concept:invisible-hand", status="indirect", evidence=[
        ev("work:general-theory", 1, "chs. 1–3, 24", "시장의 자동 완전고용 가정을 비판")]),
    rel("person:keynes", "defines", "concept:effective-demand"),
    rel("work:general-theory", "contextualized_by", "event:great-depression"),
    rel("person:hayek", "criticized", "person:keynes", evidence=[
        ev("work:hayek-review-keynes", 1, "Economica 1931", "케인스 『화폐론』 서평")]),
    rel("person:keynes", "responds_to", "person:hayek", evidence=[
        ev("J. M. Keynes, 'The Pure Theory of Money: A Reply to Dr. Hayek', Economica (Nov. 1931)", 1, "")]),
    rel("person:smith", "influenced", "person:hayek", evidence=[
        ev("work:constitution-of-liberty", 1, "ch. 4", "스미스·퍼거슨의 진화적 질서 전통을 계승")]),
    rel("concept:invisible-hand", "transformed_into", "concept:spontaneous-order", status="indirect", evidence=[
        ev("work:constitution-of-liberty", 1, "ch. 4")]),
    rel("person:hayek", "defines", "concept:spontaneous-order"),
    rel("person:hayek", "defines", "concept:dispersed-knowledge"),
    rel("person:hayek", "criticized", "concept:central-planning", evidence=[
        ev("work:road-to-serfdom", 1, ""), ev("work:use-of-knowledge", 1, "")]),
    rel("work:road-to-serfdom", "contextualized_by", "event:world-war-2"),

    # ============================================= 19세기 → 20세기 대륙
    rel("person:schopenhauer", "influenced", "person:nietzsche", evidence=[
        ev("work:untimely-schopenhauer", 1, "", "쇼펜하우어를 교육자로 찬양")]),
    rel("person:nietzsche", "criticized", "person:schopenhauer", evidence=[
        ev("work:genealogy-of-morals", 1, "III §§5–7", "금욕주의적 이상과 동정의 윤리 비판"),
        ev("source:kaufmann-nietzsche", 3, "")]),
    rel("concept:will-schopenhauer", "transformed_into", "concept:will-to-power", evidence=[
        ev("source:kaufmann-nietzsche", 3, "ch. 6", "생에 대한 부정에서 긍정으로의 전환")]),
    rel("person:nietzsche", "criticized", "person:plato", evidence=[
        ev("work:twilight-of-idols", 1, "How the 'True World' Finally Became a Fable"),
        ev("work:beyond-good-and-evil", 1, "Preface")]),
    rel("person:nietzsche", "rejected", "concept:forms", evidence=[
        ev("work:twilight-of-idols", 1, "")]),
    rel("person:nietzsche", "rejected", "concept:free-will", evidence=[
        ev("work:beyond-good-and-evil", 1, "§21")]),
    rel("person:nietzsche", "defines", "concept:will-to-power"),
    rel("person:nietzsche", "defines", "concept:eternal-recurrence"),
    rel("person:nietzsche", "defines", "concept:master-slave-morality"),
    rel("person:husserl", "defines", "concept:phenomenology-concept"),
    rel("person:husserl", "defines", "concept:epoche"),
    rel("person:husserl", "influenced", "person:heidegger", evidence=[
        ev("work:being-and-time", 1, "Dedication; §7 n.", "후설에게 헌정, 현상학적 방법의 빚을 명시")]),
    rel("person:heidegger", "reinterpreted", "concept:phenomenology-concept", evidence=[
        ev("work:being-and-time", 1, "§7", "현상학을 존재론의 방법으로 재정의")]),
    rel("person:kierkegaard", "influenced", "person:heidegger", evidence=[
        ev("work:being-and-time", 1, "§45 n.; §68 n.", "불안·순간 개념에서 키르케고르 언급")]),
    rel("person:nietzsche", "influenced", "person:heidegger", evidence=[
        ev("work:nietzsche-lectures", 1, "", "1936–46년 니체 강의")]),
    rel("person:heidegger", "defines", "concept:dasein"),
    rel("person:heidegger", "defines", "concept:authenticity"),
    rel("person:heidegger", "influenced", "person:sartre", evidence=[
        ev("work:being-and-nothingness", 1, "Introduction; Part I", "하이데거 개념을 광범위하게 사용")]),
    rel("person:husserl", "influenced", "person:sartre", evidence=[
        ev("work:being-and-nothingness", 1, "Introduction", "지향성 개념의 수용")]),
    rel("concept:phenomenology-concept", "transformed_into", "concept:existentialism-concept", status="indirect", evidence=[
        ev("work:being-and-nothingness", 1, "subtitle", "'현상학적 존재론 시론'")]),
    rel("person:sartre", "modified", "concept:authenticity", evidence=[
        ev("work:being-and-nothingness", 1, "Part I ch. 2, final note", "자기기만과 본래성")]),
    rel("person:kierkegaard", "influenced", "person:sartre", evidence=[
        ev("J.-P. Sartre, 'Kierkegaard: The Singular Universal' (1964)", 1, "")]),
    rel("person:sartre", "defines", "concept:existentialism-concept"),
    rel("person:sartre", "defines", "concept:existential-freedom"),
    rel("person:sartre", "defines", "concept:bad-faith"),
    rel("work:being-and-nothingness", "contextualized_by", "event:world-war-2"),
    rel("person:camus", "criticized", "person:kierkegaard", evidence=[
        ev("work:myth-of-sisyphus", 1, "Philosophical Suicide")]),
    rel("person:nietzsche", "influenced", "person:camus", evidence=[
        ev("work:the-rebel", 1, "Part II: Nietzsche and Nihilism")]),
    rel("person:sartre", "criticized", "person:camus", evidence=[
        ev("J.-P. Sartre, 'Réponse à Albert Camus', Les Temps Modernes (Aug. 1952)", 1, "", "『반항하는 인간』 논쟁"),
        ev("source:aronson-camus-sartre", 3, "")]),
    rel("person:camus", "defines", "concept:absurd"),
    rel("work:myth-of-sisyphus", "contextualized_by", "event:world-war-2"),

    # ======================================================= 분석철학·과학철학
    rel("person:russell", "influenced", "person:wittgenstein", evidence=[
        ev("work:tractatus", 1, "Preface", "프레게의 저작과 '나의 친구 러셀'의 저작에 빚졌다고 명시"),
        ev("source:monk-wittgenstein", 3, "chs. 2–3")]),
    rel("work:tractatus", "contextualized_by", "event:world-war-1", evidence=[
        ev("source:monk-wittgenstein", 3, "chs. 6–7", "오스트리아군 복무 중 원고 완성")]),
    rel("person:russell", "defines", "concept:logical-analysis"),
    rel("person:russell", "defines", "concept:logicism"),
    rel("person:wittgenstein", "defines", "concept:picture-theory"),
    rel("person:wittgenstein", "defines", "concept:language-game"),
    rel("work:philosophical-investigations", "criticized", "work:tractatus", evidence=[
        ev("work:philosophical-investigations", 1, "Preface", "첫 책에 '심각한 오류'가 있었다고 인정")]),
    rel("concept:picture-theory", "transformed_into", "concept:language-game", evidence=[
        ev("work:philosophical-investigations", 1, "Preface; §§1–43")]),
    rel("person:wittgenstein", "influenced", "person:kuhn", evidence=[
        ev("work:structure-scientific-revolutions", 1, "ch. V", "가족유사성 개념으로 패러다임의 규칙 없는 통일성을 설명")]),
    rel("person:hume", "influenced", "person:popper", evidence=[
        ev("work:conjectures-refutations", 1, "ch. 1", "흄의 귀납 문제를 자신의 출발점으로 서술"),
        ev("work:logic-scientific-discovery", 1, "§1")]),
    rel("person:popper", "defines", "concept:falsifiability"),
    rel("person:popper", "defines", "concept:open-society"),
    rel("person:popper", "criticized", "person:plato", evidence=[
        ev("work:open-society", 1, "Vol. I: The Spell of Plato")]),
    rel("person:popper", "criticized", "person:hegel", evidence=[
        ev("work:open-society", 1, "Vol. II ch. 12")]),
    rel("person:popper", "criticized", "person:marx", evidence=[
        ev("work:open-society", 1, "Vol. II chs. 13–21")]),
    rel("work:open-society", "contextualized_by", "event:world-war-2"),
    rel("person:kuhn", "responds_to", "person:popper", evidence=[
        ev("work:logic-or-psychology", 1, "")]),
    rel("person:popper", "criticized", "person:kuhn", evidence=[
        ev("K. Popper, 'Normal Science and its Dangers' (1970)", 1, "in Lakatos & Musgrave (eds.)")]),
    rel("person:kuhn", "defines", "concept:paradigm"),

    # =============================================== 자유 개념의 계보
    rel("person:hobbes", "defines", "concept:negative-freedom"),
    rel("person:mill", "defines", "concept:harm-principle"),
    rel("person:mill", "extended", "concept:negative-freedom", evidence=[
        ev("work:on-liberty", 1, "ch. 1")]),
    rel("person:berlin", "responds_to", "person:mill", evidence=[
        ev("work:two-concepts-of-liberty", 1, "II", "밀의 자유론을 소극적 자유의 전형으로 논의")]),
    rel("person:berlin", "responds_to", "person:hobbes", evidence=[
        ev("work:two-concepts-of-liberty", 1, "II")]),
    rel("person:berlin", "criticized", "concept:positive-freedom", evidence=[
        ev("work:two-concepts-of-liberty", 1, "III–IV", "'진정한 자아'의 이름으로 강제를 정당화할 위험")]),
    rel("person:berlin", "criticized", "person:rousseau", evidence=[
        ev("work:two-concepts-of-liberty", 1, "IV", "'자유롭도록 강제된다'는 논리 비판")]),
    rel("person:berlin", "defines", "concept:positive-freedom"),
    rel("person:mill", "defines", "concept:utilitarianism"),
    rel("school:utilitarianism", "defines", "concept:utilitarianism"),

    # ================================================================ 롤스
    rel("person:locke", "influenced", "person:rawls", evidence=[
        ev("work:theory-of-justice", 1, "§3", "로크·루소·칸트의 사회계약론을 일반화한다고 명시")]),
    rel("person:rousseau", "influenced", "person:rawls", evidence=[ev("work:theory-of-justice", 1, "§3")]),
    rel("person:kant", "influenced", "person:rawls", evidence=[
        ev("work:theory-of-justice", 1, "§3; §40 'The Kantian Interpretation of Justice as Fairness'")]),
    rel("concept:social-contract-concept", "transformed_into", "concept:justice-as-fairness", evidence=[
        ev("work:theory-of-justice", 1, "§3")]),
    rel("person:rawls", "criticized", "concept:utilitarianism", evidence=[
        ev("work:theory-of-justice", 1, "§§5, 30")]),
    rel("person:rawls", "defines", "concept:justice-as-fairness"),
    rel("person:rawls", "defines", "concept:veil-of-ignorance"),

    # =================================================== 학파가 정의하는 개념
    rel("school:continental-rationalism", "defines", "concept:rationalism"),
    rel("school:continental-rationalism", "defines", "concept:innate-ideas"),
    rel("school:british-empiricism", "defines", "concept:empiricism"),
    rel("school:british-empiricism", "defines", "concept:tabula-rasa"),
    rel("school:german-idealism", "defines", "concept:idealism"),
    rel("school:marxism", "defines", "concept:class-struggle"),
    rel("school:marxism", "defines", "concept:materialism"),
    rel("school:classical-economics", "defines", "concept:labor-theory-of-value"),
    rel("school:austrian-school", "defines", "concept:spontaneous-order"),
    rel("school:stoicism", "defines", "concept:inner-freedom"),
    rel("school:epicureanism", "defines", "concept:ataraxia"),
    rel("school:critical-rationalism", "defines", "concept:falsifiability"),
    rel("school:analytic-philosophy", "defines", "concept:logical-analysis"),
    rel("school:phenomenology", "defines", "concept:phenomenology-concept"),
    rel("school:existentialism", "defines", "concept:existentialism-concept"),
    rel("school:keynesianism", "defines", "concept:effective-demand"),
    rel("school:liberalism", "defines", "concept:negative-freedom"),
    rel("school:liberalism", "defines", "concept:individualism"),
    rel("school:natural-law-tradition", "defines", "concept:natural-law"),
    rel("school:social-contract", "defines", "concept:social-contract-concept"),
    rel("school:enlightenment", "defines", "concept:enlightenment-concept"),
    rel("school:platonism", "defines", "concept:forms"),
    rel("school:aristotelianism", "defines", "concept:hylomorphism"),
    rel("school:scholasticism", "defines", "concept:natural-law"),

    # ====================================================== 동시대 관계
    rel("person:hegel", "contemporary_with", "person:schopenhauer", evidence=[
        ev("source:copleston", 3, "Vol. VII", "1820년 베를린 대학에서 쇼펜하우어가 헤겔과 같은 시간에 강의를 개설")]),
    rel("person:hume", "contemporary_with", "person:rousseau", evidence=[
        ev("source:copleston", 3, "Vol. V", "1766년 영국 체류와 결별")]),
    rel("person:hume", "contemporary_with", "person:smith"),
    rel("person:leibniz", "contemporary_with", "person:newton"),
    rel("person:spinoza", "contemporary_with", "person:leibniz"),
    rel("person:russell", "contemporary_with", "person:wittgenstein"),
    rel("person:keynes", "contemporary_with", "person:hayek"),
    rel("person:popper", "contemporary_with", "person:kuhn"),
    rel("person:sartre", "contemporary_with", "person:camus"),
    rel("person:popper", "contemporary_with", "person:hayek"),
]

# 명제 간 관계 (prop key, predicate, prop key, epistemic, evidence, note)
PROPOSITION_RELATIONS = [
    ("locke-white-paper", "contradicted_by", "leibniz-veins-marble", "accepted",
     [ev("work:new-essays", 1, "Preface")], ""),
    ("plato-cave", "contradicted_by", "aristotle-critique-forms", "accepted",
     [ev("work:metaphysics", 1, "A.9")], ""),
    ("augustine-free-will", "contradicted_by", "spinoza-no-free-will", "accepted", [], ""),
    ("hobbes-state-of-war", "contradicted_by", "rousseau-natural-man", "accepted",
     [ev("work:discourse-inequality", 1, "Part I")], ""),
    ("newton-absolute-space", "contradicted_by", "leibniz-relational-space", "accepted",
     [ev("work:leibniz-clarke", 1, "")], ""),
    ("newton-absolute-space", "contradicted_by", "einstein-no-ether", "accepted",
     [ev("work:special-relativity", 1, "")], ""),
    ("aristotle-private-property", "contradicted_by", "marx-abolish-property", "accepted", [], ""),
    ("locke-property-labor", "contradicted_by", "marx-abolish-property", "accepted", [], ""),
    ("rousseau-forced-free", "contradicted_by", "berlin-two-concepts", "accepted",
     [ev("work:two-concepts-of-liberty", 1, "IV")], ""),
    ("popper-falsifiability", "contradicted_by", "kuhn-paradigm", "proposed",
     [ev("work:logic-or-psychology", 1, "")], "부분적 대립 — 쿤은 반증의 역할을 부정하지 않고 위치를 옮김"),
    ("plato-cave", "contradicted_by", "nietzsche-true-world-fable", "accepted",
     [ev("work:twilight-of-idols", 1, "")], ""),
    ("smith-invisible-hand", "contradicted_by", "keynes-effective-demand", "proposed", [],
     "케인스는 '보이지 않는 손' 자체보다 자동적 완전고용 가정을 겨냥"),
    ("kierkegaard-teleological-suspension", "contradicted_by", "camus-philosophical-suicide", "accepted",
     [ev("work:myth-of-sisyphus", 1, "Philosophical Suicide")], ""),
    ("mill-greatest-happiness", "contradicted_by", "rawls-against-utilitarianism", "accepted",
     [ev("work:theory-of-justice", 1, "§5")], ""),
    ("hume-induction", "supports", "popper-solution-induction", "accepted", [], ""),
    ("hume-induction", "supports", "kant-dogmatic-slumber", "accepted", [], ""),
    # 구조적 유사성 (영향을 함의하지 않음)
    ("plato-city-division-of-labor", "similar_to", "smith-division-of-labor", "accepted",
     [ev("work:capital", 1, "ch. 14 §5 n.", "마르크스가 플라톤의 분업론을 고전파와 나란히 논의 — 비교의 근거이지 영향의 증거는 아님")],
     "구조적 유사성 — 스미스가 플라톤에게서 빌려 왔다는 원전 증거 없음"),
    ("augustine-si-fallor", "similar_to", "descartes-cogito", "accepted",
     [ev("work:meditations", 1, "Fourth Objections (Arnauld)")], ""),
    ("spinoza-freedom-to-philosophize", "similar_to", "mill-freedom-of-thought", "accepted", [], ""),
    ("epictetus-control", "similar_to", "spinoza-freedom", "proposed", [],
     "통제 가능한 것에 대한 앎으로서의 자유 — 구조적 유사성"),
    ("hegel-history-freedom", "similar_to", "marx-realm-of-freedom", "accepted", [], ""),
    ("aristotle-money-measure", "similar_to", "aquinas-just-price", "accepted",
     [ev("work:summa-theologiae", 1, "II-II q.77 a.1")], ""),
    ("hayek-spontaneous-order", "similar_to", "smith-invisible-hand", "accepted",
     [ev("work:constitution-of-liberty", 1, "ch. 4")], ""),
    ("leibniz-reminiscence", "similar_to", "plato-recollection", "accepted",
     [ev("work:discourse-on-metaphysics", 1, "§26")], ""),
]

# 가설 예시: 스토아 → 스피노자
EXTRA_HYPOTHESES = [
    rel("person:epictetus", "influenced", "person:spinoza", status="inferred", epistemic="hypothesis", origin="ai",
        evidence=[ev("HIGO discovery engine (seed example)", 6, "",
                     "『엥케이리디온』 1장과 『에티카』 I 정의 7의 자유 개념 유사성에서 추론 — 근세 신스토아주의(립시우스 등)를 매개로 한 경로 검토 필요")]),
]

# 해석 (id, label_ko, held_by, interprets, about, description, stance-note)
INTERPRETATIONS = [
    ("interp:strauss-locke", "로크의 숨은 홉스주의 (슈트라우스)", "source:strauss-nrh", "person:locke",
     ["natural-rights", "natural-law"],
     "로크의 자연법 교설은 전통적 외양 아래 홉스적 자기보존의 권리론을 담고 있다는 해석. 논쟁적."),
    ("interp:popper-plato", "전체주의자로서의 플라톤 (포퍼)", "person:popper", "work:republic",
     ["ideal-state", "open-society"],
     "『국가』의 이상국가론을 닫힌사회·전체주의의 원형으로 읽는 해석. 고전학계의 강한 반론이 있음."),
]
