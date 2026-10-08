# S6-3 heading-detection accuracy check

Rule: a chunk's heading is correct if its part title is the right document part and its section is the nearest real heading governing the start of the chunk (or, when no section governs the start, the first one opened inside it).

## Detector v1 (src/structure.py sha256 c8134b30...), sample random.Random(63).sample(30): 25/30 correct (83%)
Fixed in v2 (general rules, before any index build): wrapped programme titles holding a code, 'CODE - Title' module lines, module titles at the end of a chunk. Not fixed: list items read as part titles.

- [✗] chunk 494 (MSU Humanities Yearbook, p. 122): `Section: FACULTY OF EDUCATION > 4 FACULTY OF SOCIAL SCIENCES` — wrong: part and section come from a list of faculties
- [✓] chunk 547 (MSU Humanities Yearbook, p. 133): `Section: GENERAL ACADEMIC REGULATIONS FOR UNDERGRADUATE DEGREES > 9 DETERMINATION OF CANDIDATES' RESULTS`
- [✗] chunk 984 (MSU Humanities Yearbook, p. 206): `Section: REGULATIONS FOR THE MASTER OF ARTS DEGREE IN DEVELOPMENT PRACTICE (AH17) > MADP 724 Advanced Strategic Management for Development Entities` — wrong: governing module is MADP 825 ('CODE - Title' form not recognised)
- [✓] chunk 1211 (MSU Humanities Yearbook, p. 236): `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN ARCHIVAL AND HISTORICAL > AHIM 442 Trends in Digital Archives Management`
- [✓] chunk 1235 (MSU Humanities Yearbook, p. 239): `Section: REGULATIONS FOR THE MASTER OF ARTS DEGREE IN AFRICAN HISTORY (MAAH) > MAAH 720 History of Medicine and IKS in Africa`
- [✓] chunk 1286 (MSU Humanities Yearbook, p. 248): `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN ENGLISH AND COMMUNICATION > BAEH 233 Language Policy and Planning`
- [✓] chunk 1426 (MSU Humanities Yearbook, p. 270): `Section: REGULATIONS FOR THE MASTER OF ARTS DEGREE IN AFRICAN LANGUAGES AND CULTURE > 1 PURPOSE OF THE PROGRAMME`
- [✓] chunk 2096 (MSU Humanities Yearbook, p. 381): `Section: REGULATIONS FOR BACHELOR OF EDUCATION HONOURS DEGREE IN PRIMARY EDUCATION AND > 13.0 Programme structure > LEVEL 1 SEMESTER 2`
- [✓] chunk 2671 (MSU Humanities Yearbook, p. 473): `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION DUAL HONOURS DEGREE IN COMMERCE AND > 7.0 GENERAL PROVISIONS`
- [✓] chunk 3317 (MSU Humanities Yearbook, p. 576): `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN PHYSICAL > SEPS 104 Generic Games' Skill: Theory and Practice`
- [✓] chunk 3644 (MSU Humanities Yearbook, p. 629): `Section: REGULATIONS FOR THE MASTER OF LAWS IN CONSTITUTIONAL AND HUMAN RIGHTS LAW (LLM) > 2 OBJECTIVES`
- [✓] chunk 3732 (MSU Humanities Yearbook, p. 641): `Section: REGULATIONS FOR THE DIPLOMA IN PARALEGAL STUDIES (DPLS) > DPLS 203 Paralegal Ethics`
- [✓] chunk 3847 (MSU Humanities Yearbook, p. 660): `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN DEVELOPMENTAL PSYCHOLOGY (HDP) > PSY 134 Human Diversity`
- [✓] chunk 4144 (MSU Humanities Yearbook, p. 706): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN ANTHROPOLOGY (ANTH) > ANTH 207 Anthropology of Industrialisation and Industrial Life`
- [✓] chunk 4485 (MSU Humanities Yearbook, p. 755): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN ENVIRONMENTAL DISASTER RISK MANAGEMENT AND RESILIENCE BUILDING > 2.0 ENTRY REQUIREMENTS`
- [✓] chunk 4764 (MSU Humanities Yearbook, p. 796): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN POLITICAL SCIENCE AND GOVERNANCE (HPSG) > HPSG 105 Political Economy of Zimbabwe`
- [✓] chunk 4818 (MSU Humanities Yearbook, p. 805): `Section: REGULATIONS FOR POSTGRADUATE DIPLOMA IN PUBLIC MANAGEMENT AND LEADERSHIP > DPML 602 Management And Leadership Theories`
- [✓] chunk 5029 (MSU Humanities Yearbook, p. 841): `Section: REGULATIONS FOR BACHELOR OF SCIENCE IN MUSIC BUSINESS, MUSICOLOGY AND TECHNOLOGY HONOURS DEGREE (MBMT) > 13.0 PROGRAMME STRUCTURE > Level 4 Semester 2`
- [✓] chunk 5376 (MSU Humanities Yearbook, p. 897): `Section: REGULATIONS FOR UNDERGRADUATE DIPLOMA IN SOCIAL WORK (UDSWK) > SOC 139 Introduction to Social Anthropology`
- [✓] chunk 6335 (MSU Sciences Yearbook Vol. 2, p. 256): `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN AGRONOMY MAJORING IN CROP IMPROVEMENT AND SEED PRODUCTION > AGHORT 439 Seed Technologies`
- [✓] chunk 7010 (MSU Sciences Yearbook Vol. 2, p. 390): `Section: REGULATIONS FOR THE BACHELOR OF COMMERCE HONOURS DEGREE IN > ACC 452 Applied Cost and Management Accounting II`
- [✗] chunk 7278 (MSU Sciences Yearbook Vol. 2, p. 438): `Section: REGULATIONS FOR THE BACHELOR OF COMMERCE HONOURS DEGREE IN > 2.1 Normal Entry` — wrong: programme title cut off before '(BS09)' line
- [✓] chunk 7293 (MSU Sciences Yearbook Vol. 2, p. 441): `Section: REGULATIONS FOR THE BACHELOR OF COMMERCE HONOURS DEGREE IN > EC 134 Economic Principles II`
- [✓] chunk 7934 (MSU Sciences Yearbook Vol. 2, p. 561): `Section: REGULATIONS FOR THE MASTER OF COMMERCE DEGREE IN STRATEGIC > MBM 771 Management Accounting`
- [✓] chunk 9103 (MSU Sciences Yearbook Vol. 2, p. 803): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN CHEMICAL TECHNOLOGY (HCT) > HCT 238 Industrial Chemistry II`
- [✓] chunk 9776 (MSU Sciences Yearbook Vol. 2, p. 941): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING (HAIML) > 3 PROGRAMME CHARACTERISTICS`
- [✗] chunk 9815 (MSU Sciences Yearbook Vol. 2, p. 948): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING (HAIML) > HAIML 212 Deep Learning` — wrong: governing module HCSEC 221 is the last line of the previous chunk
- [✗] chunk 10013 (MSU Sciences Yearbook Vol. 2, p. 988): `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN ACTUARIAL SCIENCES (HACS) > HSTAT 105 Regression and Analysis of Variance 1` — wrong: governing module HACS 231 missed (description starts on a short line)
- [✓] chunk 10042 (MSU Sciences Yearbook Vol. 2, p. 992): `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN ACTUARIAL SCIENCES (HACS) > HACS 337 Computational Finance`
- [✓] chunk 10292 (MSU Sciences Yearbook Vol. 2, p. 1045): `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN APPLIED SCIENCES AND NANOTECHNOLOGY (HNN) > 1.0 PURPOSE OF THE PROGRAMME`

## Detector v2 (used for faiss_store_v2; sha256 d9a0c607...), fresh sample random.Random(64).sample(30): 24/30 correct (80%); section only: 25/30

Each case: assigned heading, then the start of the chunk and the short lines from the chunks just before it, so the governing heading can be checked.

### [✓] chunk 87 — MSU Humanities Yearbook, p. 25
- **Assigned:** `Section: MIDLANDS STATE UNIVERSITY ACT > 27 Student Disciplinary Committee`
- **Chunk starts:** (b) the withdrawal of any academic or University privilege, benefit, right or facility other than to follow | courses of instruction and present himself for examination; | (c) the imposition of a fine not exceeding level 3, which fine may be deducted from any allowances payable | to the student and shall be paid to the University; | [Amended by Act
- **Preceding short lines:** [84] 27 Student Disciplinary Committee / [84] Vice-Chancellor¾

### [✗] chunk 276 — MSU Humanities Yearbook, p. 77
- **Assigned:** `Section: FACULTY OF ENGINEERING AND GEOSCIENCES > 3 Faculty of Built Environment, Art and Design`
- **My judgement:** wrong: chunk is a front-matter list of faculties; part and section are list items
- **Chunk starts:** Faculty of Education | Department of Adult Education | Department of Curriculum and Arts Education | Department of Educational Administration Department of Educational Foundations | Faculty of Engineering
- **Preceding short lines:** [275] Department of Fashion and Textiles / [275] Department of Visual and Performing Arts / [275] Faculty of Commerce and Information Systems / [275] Department of Accounting / [275] Department of Business Studies / [275] Department of Insurance / [275] Department of Tourism Studies / [275] Department of Economics

### [✗] chunk 403 — MSU Humanities Yearbook, p. 101
- **Assigned:** `Section: FACULTY OF ENGINEERING AND GEOSCIENCES > 5.4 Experience`
- **My judgement:** wrong part (stale faculty name from a list); section 5.4 Experience is right
- **Chunk starts:** 5.4 Experience | 5.4.1 In granting recognition to relevant postgraduate experience, the University shall: | 5.4.1.1 Make no distinction to relevance between professional and non-professional experience. | 5.4.1.2 Recognise in full, the time spent as a full-time member of staff of a reputable university or | tertiary organisation.
- **Preceding short lines:** [401] Communications Officer; Events Coordinator; Transport & Logistics / [401] Officer; Clothing Supervisor; Artisan Supervisor; Printer; Central Services / [401] Campus Supervisor; Deputy Chaplain; Deputy Sports Coordinator; Full- / [401] Time Warden; Head Chefs; Environmental Health Technician; Internal / [401] Audit Assistant; Procurement Specialist; HR Officer; Industrial Relations / [401] Officer; Welfare Officer; HR Systems Coordinator / [402] 5. GRADING AND APPOINTMENT / [402] 5.3 Qualifications

### [✓] chunk 749 — MSU Humanities Yearbook, p. 172
- **Assigned:** `Section: REGULATIONS FOR THE MASTER OF ARTS DEGREE IN ARCHAEOLOGY (MARC) > MARC 715 Field Archaeology (Field School)`
- **Chunk starts:** students with basic fieldwork knowledge and skills in archaeological research. These include research design, | planning, archaeological survey, excavation, sorting of finds and documentation of archaeological sites. Students | will be taken through the rigorous processes and approaches that constitute archaeological fieldwork. Students will | spen
- **Preceding short lines:** [744] MARC 710 Geographical Information Systems in Archaeology II / [745] MARC 711 Rock Art of Africa / [746] MARC 712 Archaeology and Ethnicity / [746] Countries. / [746] MARC 713 Theoretical Approaches in World Archaeology / [747] MARC 714 Archaeometallurgy: Mining and Extractive Technology / [748] MARC 715 Field Archaeology (Field School)

### [✓] chunk 1045 — MSU Humanities Yearbook, p. 216
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN HISTORY AND INTERNATIONAL STUDIES HONOURS (AH06) > HISH 233 Europe between 1789 and 1918`
- **Chunk starts:** Italy and Germany occupies a special position. The module also looks at how European diplomacy played out resulting in | the formation of two hostile camps, the Triple Entente and the Triple Alliance. The module ends with an examination of | the causes, course and results of the so-called World War I of 1914-1918.
- **Preceding short lines:** [1040] HISH 230 History of Zimbabwe 1890-1980 / [1041] House Agreement and the coming of Uhuru-independence / [1042] HISH 232 Historiography and Historical Methods / [1044] HISH 233 Europe between 1789 and 1918

### [✓] chunk 1307 — MSU Humanities Yearbook, p. 250
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN ENGLISH AND COMMUNICATION > BAEH 442 Bilingualism`
- **Chunk starts:** BAEH 442 Bilingualism | The module is an exploration of the notion of bilingualism. As such, effort is put into understanding the nature of | bilingualism, and the causes and effects of bilingualism. Focus is also on the different forms of bilingualism and debates | on the impact and/ or implication of bilingualism in societies, individuals, educat
- **Preceding short lines:** [1302] BAEH 444 Globalisation and International Communication / [1303] BAEH 445 Theoretical Approaches to Multi-modal Texts / [1305] BAEH 446 Occupational Discourses

### [✓] chunk 1370 — MSU Humanities Yearbook, p. 260
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN LANGUAGE AND CULTURAL STUDIES (AH07) > HALCS 204 Children's Literature and Children's Development`
- **Chunk starts:** HALCS 204 Children's Literature and Children's Development | This module is preoccupied with a critical appreciation of children's literature in Africa with a view to understanding the | different ways in which literature is deployed to the business of empowering the young in society. Theories are deployed | to the analysis of such literature in Af
- **Preceding short lines:** [1366] HCS 135 Introduction to Information Technology / [1366] Refer to the Department of Information Systems. / [1366] CS 131 Basic Communication Skills / [1367] CS 131 Basic Communication Skills / [1367] HALCS 114 Basic French II / [1368] HALCS 201 African Indigenous Knowledge Systems / [1369] HALCS 202 Language, Culture and Identity / [1369] HALCS 203 Intercultural Communication

### [✗] chunk 1727 — MSU Humanities Yearbook, p. 321
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF ARTS HONOURS DEGREE IN RELIGIOUS AND FAMILY STUDIES > 2.3 Mature entry`
- **My judgement:** wrong (minor): chunk starts with the end of 2.2 Special entry; 2.3 was taken from the overlap with the previous chunk
- **Chunk starts:** level or its equivalent. Candidates with relevant work experience may also be admitted. | 2.3 Mature entry | • Persons who are 25 years of age for males and 23 years for females may apply for mature entry provided they passed at least 5 'O' levels | including English and must have demonstrated suitability for university studies by virtue of their a
- **Preceding short lines:** [1725] Level: / [1725] ZNQF-Level 8 / [1725] 1.0 PURPOSE OF THE PROGRAMME / [1726] 2.0 ENTRY REQUIREMENTS / [1726] 2.1 Normal Entry / [1726] English and any other relevant subject in the Humanities. / [1726] 2.2 Special entry / [1726] 2.3 Mature entry

### [✓] chunk 2045 — MSU Humanities Yearbook, p. 371
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN INCLUSIVE EDUCATION AND ASSISTIVE TECHNOLOGIES (EDU12) > 4.0 CAREER OPPORTUNITIES AND FURTHER EDUCATION`
- **Chunk starts:** 4.0 CAREER OPPORTUNITIES AND FURTHER EDUCATION | Employability: Graduates can be employed as supervisors, special care unit managers, teachers, education officers, | curriculum developers, consultants, remedial tutors etc. | Further Studies: Master's and Doctoral Studies in Inclusive Education and Assistive Technologies | 5.0 PROGRAMME DELIVERY | T
- **Preceding short lines:** [2042] Minimum Credit Load / [2042] Maximum Credit Load / [2042] Total MBKs Credit Load / [2042] ZNQF Level / [2043] 1.0 PURPOSE OF THE PROGRAMME / [2043] 2.0 ENTRY REQUIREMENTS / [2043] 3.0 PROGRAMME CHARACTERISTICS / [2043] Areas of Study: Inclusive Education

### [✓] chunk 2415 — MSU Humanities Yearbook, p. 432
- **Assigned:** `Section: REGULATIONS FOR MASTER OF EDUCATION DEGREE IN EARLY CHILDHOOD DEVELOPMENT AND CHILD PROTECTION (EDU07) > MECDP 704 Management of Early Childhood Programmes`
- **Chunk starts:** MECDP 704 Management of Early Childhood Programmes | This module examines issues and responsibilities related to the management of early childhood development programmes. | It enables students to develop knowledge, skills and attitudes in the management of programmes for young children. The | module focuses on general theories and practices of mana
- **Preceding short lines:** [2410] MED744 / [2410] Dissertation / [2410] 13. MODULE SYNOPSES / [2410] MECDP701 Theories of Child Development in Socio- Cultural Contexts / [2411] MECDP 702 Curriculum Innovation and Industrialisation in Early Childhood Development / [2412] MED731 Advanced Research Methods and Statistics / [2413] MICT 732 Advanced Information Communication Technology in Education / [2414] MECDP 703 Pertinent Contemporary Issues in Early Childhood Development

### [✓] chunk 2860 — MSU Humanities Yearbook, p. 504
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN INDIGENOUS LANGUAGES, KNOWLEDGE SYSTEMS AND MULTICULTURALISM (EDU24) > IKSM 206 Contemporary Issues in Education`
- **Chunk starts:** IKSM206 Contemporary Issues in Education | The module exposes students to the most current global trends like Globalisation, Millennium development goals, Gender, | Human rights, and Health pandemics how they feed into Agenda 2030 and also how they affect the Zimbabwean Education | system. The thrust is to leverage current trends in promoting innov
- **Preceding short lines:** [2855] BEFM231 School Administration and Financial Management in Education / [2856] BED132 Applied Educational Foundations / [2857] IKSM205 Developments and Innovations in African Oral Literature and Philosophies of Life / [2858] IKSM206 Languages, dialects and linguistic diversity in Zimbabwe / [2859] BED232 Research Project

### [✓] chunk 3248 — MSU Humanities Yearbook, p. 566
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN MATHEMATICS AND APPLIED STATISTICS (EDU26) > AECS 131 Introduction to Information Communication Technology`
- **Chunk starts:** AECS131: Introduction to Information Communication Technology | This module guides students to critically and creatively apply concepts, principles, hardware and software associated | with the infusion of information communication technology (ICT) in solving educational problems and meeting | challenges in their roles as facilitators of learning. T
- **Preceding short lines:** [3243] SEM106: Complex Numbers and Vectors / [3244] SEM107: Coordinate and Analytic Geometry / [3244] SEM108: Algebra and Functions / [3245] EFA331/332/333: Applied Educational Foundations / [3246] CS131: Basic Communication Skills / [3247] BCHS131: Culture and Heritage Studies

### [✓] chunk 3299 — MSU Humanities Yearbook, p. 573
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN MATHEMATICS AND APPLIED STATISTICS (EDU26) > SEMA 203 Statistical Inference`
- **Chunk starts:** SEMA203: Statistical Inference | The module covers population and sample concepts as the basis of statistical inference, parameters and statistics, review of | probability theory, Central Limit Theorem, Chi-square, student-t and F distributions, distribution of min and max, | estimation, interval estimation, confidence intervals, hypothesis testing
- **Preceding short lines:** [3294] EDGS231: Gender Studies for Educators / [3295] SEMA201: Introduction to Discrete Mathematics / [3295] BEIE501: Entrepreneurship and Industrialisation in Education / [3297] SEMA202: Advanced Pedagogics in Mathematics / [3298] EFS131 & EFPS131 & EFPH131: Applied Educational Foundations

### [✓] chunk 3334 — MSU Humanities Yearbook, p. 579
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF EDUCATION HONOURS DEGREE IN PHYSICS AND APPLIED TECHNOLOGIES (EDU74) > 7.0 GENERAL PROVISIONS > Level 1 Semester 1`
- **Chunk starts:** 7.0 GENERAL PROVISIONS | • For the Bachelor of Education Degree programme, candidates shall study at least 23 modules. | • Each module is worth 12 credits except for the project which is worth 24 credits. | • 8.0 ASSESSMENT | Refer to Section 4 of the Faculty Regulations. | 9.0 PROVISION FOR PROGRESSION
- **Preceding short lines:** [3332] Orientation: / [3332] 4.0 CAREER OPPORTUNITIES AND FURTHER EDUCATION / [3332] Employability: / [3332] Further Studies: / [3332] Master's and Doctoral studies in Physics Education / [3332] 5.0 PROGRAMME DELIVERY / [3332] Teaching and Learning Methods: / [3333] 6.0 LEARNING OUTCOMES

### [✗] chunk 3592 — MSU Humanities Yearbook, p. 622
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF LAWS HONOURS DEGREE (LLBS) > 6 Compulsory modules plus 2 electives > Level 5 Semester 2`
- **My judgement:** wrong: '6 Compulsory modules plus 2 electives' is a table note, not a heading
- **Chunk starts:** 12 | LB523 | Energy Law | 12 | LB524
- **Preceding short lines:** [3591] LB524 / [3591] E-Commerce / [3591] LB526 / [3591] International Trade Law / [3591] LB527 / [3591] International Investment Law / [3591] LB529 / [3591] Advocacy

### [✓] chunk 4325 — MSU Humanities Yearbook, p. 732
- **Assigned:** `Section: REGULATIONS FOR MASTER OF SCIENCE DEGREE IN DEMOGRAPHY AND POPULATION STUDIES > 11.0 GRADING AND DEGREE CLASSIFICATION > Level 1 Semester 1`
- **Chunk starts:** 11.0 GRADING AND DEGREE CLASSIFICATION | Refer to section 10 of the Faculty Regulations. | 12.0 DEGREE WEIGHTING | Refer to section 11 of the Faculty Regulations.
- **Preceding short lines:** [4324] Written Examinations: / [4324] Dissertation: / [4324] 9.0 PROVISION FOR PROGRESSION / [4324] Refer to section 6 of the University's General Regulations. / [4324] 10.0 FAILURE TO SATISFY EXAMINERS / [4324] Refer to section 9 of the University's General Regulations. / [4324] 11.0 GRADING AND DEGREE CLASSIFICATION / [4324] Refer to section 10 of the Faculty Regulations.

### [✓] chunk 4401 — MSU Humanities Yearbook, p. 742
- **Assigned:** `Section: REGULATIONS FOR MASTER OF SCIENCE DEGREE IN SOCIOLOGY AND SOCIAL ANTHROPOLOGY > MSO 704 Social Policy and Administration`
- **Chunk starts:** This course focuses on examining the different perspectives on social policy and their implications for understanding and | addressing major social problems in society. The main issues to be considered include a focus on the history of social | policy, poverty, urban development, education, health, social welfare, housing, social security and inter
- **Preceding short lines:** [4396] MSO 702 Advanced Qualitative Research Methodology / [4398] MSO 703 Advanced Social Theory / [4400] MSO704 Social Policy and Administration

### [✓] chunk 6601 — MSU Sciences Yearbook Vol. 2, p. 308
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN WILDLIFE ECOLOGY AND MANAGEMENT (HWEM) > HAWS 434 Natural Resources Economics`
- **Chunk starts:** HAWS 434 Natural Resources Economics | This module develops a rationale for and explains the methodologies used in, the application of | economic theory to the allocation of natural resources. Using a series of natural resource sectors as | examples, several economic models are then explained in detail in a way that is intended to raise | the learn
- **Preceding short lines:** [6596] HAWS 431 Rangeland Ecology / [6596] Definition and description of rangelands, their characteristics and economic importance of / [6597] HAWS 435 Intensive Wildlife Production Systems / [6600] HAWS 432 Wildlife Products Processing / [6600] Handling of wildlife products and by-products, harvesting for meat, eggs, and processing.

### [✓] chunk 6618 — MSU Sciences Yearbook Vol. 2, p. 313
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN POULTRY SCIENCE (HPS) > HAWS 132 Introduction to Biochemistry`
- **Chunk starts:** HAWS 132 Introduction to Biochemistry | Energy flows in biological systems; Structure of cells; Stereochemistry: positional, geometrical and | optical isomerism; Chemistry of carbohydrates: classification, structure, functions, mobilization | and transport; Chemistry of proteins: amino acids their classification, structure, functions, | mobilizatio
- **Preceding short lines:** [6615] HAWS 459 / [6615] Poultry Products and Technology / [6615] HAWS 460 / [6615] Marketing of Poultry Products / [6616] 14.0 MODULE SYNOPSES / [6616] HAWS 140 Introduction to Poultry Science / [6616] Poultry production systems / [6617] HAWS 139 Poultry Anatomy and Physiology

### [✓] chunk 6827 — MSU Sciences Yearbook Vol. 2, p. 353
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN AGRICULTURAL WATER MANAGEMENT (HAWM) > 13 PROGRAMME STRUCTURE > Level I`
- **Chunk starts:** 12 | LWR131 | Environmental Chemistry | 12 | LWR135
- **Preceding short lines:** [6826] AGRO136 / [6826] Introduction to Statistics / [6826] LWR131 / [6826] Environmental Chemistry / [6826] LWR135 / [6826] Principles of Soil Science / [6826] AWM135 / [6826] Plant Biology and Physiology

### [✓] chunk 7209 — MSU Sciences Yearbook Vol. 2, p. 427
- **Assigned:** `Section: REGULATIONS FOR THE MASTER OF COMMERCE DEGREE IN FINANCE AND DIGITAL BANKING (BS17) > MFDB 732 Advanced Financial Econometrics and Data Analysis`
- **Chunk starts:** MFDB732 Advanced Financial Econometrics and Data Analysis | This module aims to explain how econometric methods can be used to learn about the | future behaviour of the prices of financial assets by using information on the history of | asset prices and the prices of derivative securities. The specific objectives of the course | are to introduce a 
- **Preceding short lines:** [7208] MFDB831 / [7208] Corporate Governance and Ethics / [7208] MFDB832 / [7208] SQL For Financial Data / [7208] MFDB833 / [7208] Dissertation / [7208] 13.0 MODULE SYNOPSES / [7208] MFDB731 Global Financial Markets

### [✓] chunk 7801 — MSU Sciences Yearbook Vol. 2, p. 534
- **Assigned:** `Section: REGULATIONS FOR THE MASTER OF COMMERCE DEGREE IN INFORMATION AND KNOWLEDGE MANAGEMENT (BS23) > 1 PURPOSE OF THE PROGRAMME`
- **Chunk starts:** 1. PURPOSE OF THE PROGRAMME | The goal of the programme is to educate students to manage organisation's knowledge assets. The | programme aims to develop the sound conceptual, technical, analytical and communication skills | that are required to succeed in the specification, design, construction and Information and | Knowledge systems. In addition,
- **Preceding short lines:** [7800] AND KNOWLEDGE MANAGEMENT (BS23) / [7800] Duration / [7800] 1½ years / [7800] Credit Load / [7800] Minimum Credit Load / [7800] Maximum Credit Load / [7800] Maximum MBKs Credit Load / [7800] ZNQF Level

### [✗] chunk 8784 — MSU Sciences Yearbook Vol. 2, p. 733
- **Assigned:** `Section: FACULTY OF MEDICINE AND HEALTH SCIENCES > BMS 115 Physiology 1`
- **My judgement:** wrong: governing module is BMS 116 (code and title on separate lines)
- **Chunk starts:** BMS 116 | Behavioural Sciences (Sociology and Psychology for Health Sciences) 1 | This module is an introductory to the Sociology and Psychology of Health Sciences. Students | will be exposed to the socio-behavioural-cultural perspectives to Health. Topics to be covered | include Introduction to Behavioural Sciences, Genetics and Behaviour (Western
- **Preceding short lines:** [8780] BMS 115 Physiology 1 / [8781] The Physiology module introduces Biomedical Sciences students to the foundation upon

### [✓] chunk 8834 — MSU Sciences Yearbook Vol. 2, p. 742
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF MEDICINE AND BACHELOR OF > 3 DATES OF EXAMINATIONS`
- **Chunk starts:** The professional Examinations for the Degrees of MBChB will normally take place | at the following times: | First year, MBChB Part I - in or about the 14th week of the second semester. | (Biochemistry) | Second year, MBChB Part II - in or about the 16th week of the Part II Second Year | (Anatomy, Behavioural Sciences
- **Preceding short lines:** [8833] Mathematics; / [8833] Passes at Advanced Level (or approved equivalent) in Chemistry and any two / [8833] Biology (or Zoology) / [8833] Mathematics / [8833] Physics / [8833] Level. / [8833] 3. DATES OF EXAMINATIONS / [8833] 3.1 University Examinations:

### [✓] chunk 9612 — MSU Sciences Yearbook Vol. 2, p. 912
- **Assigned:** `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN COMPUTER SYSTEMS ENGINEERING (HCSE) > HCSE 233 Linear Algebra`
- **Chunk starts:** HCSE233 Linear Algebra | This module will introduce basic concepts and techniques from linear algebra that will be | required in later modules in areas such as computer graphics and machine learning. Topics | include eigenvalues and eigenvectors, vector linear independence and bases for vector spaces, | spaces and subspaces, orthogonal vector space
- **Preceding short lines:** [9609] Requirements, Specifications and Software Design approaches, Modular Designs, CASE tools, / [9609] Case Studies. Object Oriented Analysis and Design using the Unified Modelling Language / [9610] HCSE231 Object Oriented Analysis and Design / [9610] Design; Object-Oriented Design Principles; Object-Oriented Design Patterns. / [9610] HCSE232 Engineering Statistics / [9611] HCSE232 Engineering Statistics / [9611] Data types, Presentation and Summarization techniques, Regression and Correlation, Simple / [9611] Statistical Inference.

### [✗] chunk 9648 — MSU Sciences Yearbook Vol. 2, p. 919
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN SOFTWARE ENGINEERING (HSWE) > 3 Years (Visiting)`
- **My judgement:** wrong: '3 Years (Visiting)' is a table value, not a heading
- **Chunk starts:** • Commitment to life-long learning: Graduates should realize that the | computing field advances at a rapid pace, and graduates must possess a solid | foundation that allows and encourages them to maintain relevant skills as the | field evolves.
- **Preceding short lines:** [9645] Engineering impact on society and the environment. / [9645] Software Engineering methodologies and modern project management / [9646] Software Engineering methodologies and modern project management / [9647] Solutions to many problems require both computing skills and domain

### [✓] chunk 10043 — MSU Sciences Yearbook Vol. 2, p. 993
- **Assigned:** `Section: REGULATIONS FOR THE BACHELOR OF SCIENCE HONOURS DEGREE IN ACTUARIAL SCIENCES (HACS) > HACS 337 Computational Finance`
- **Chunk starts:** Hedging and immunization; the stochastic differential equations and martingale | approach, multinomial tree and Monte Carlo methods, the partial differential | equations approach, finite difference methods.
- **Preceding short lines:** [10039] Gross premiums and provisions for fixed and variable benefit contracts; / [10039] Describe the calculation of gross premiums and reserves of assurance and annuity / [10039] Calculate gross premiums using the future loss random variable and the equivalence / [10041] HACS336: Methods of Actuarial Investigations / [10041] Capital redemption policies; determination of the rate of interest in a given / [10041] Cumulative sinking funds; yield curves; discounted mean terms; matching and / [10042] HACS337: Computational Finance / [10042] Computational methods in finance and financial modelling; interest rate models and

### [✓] chunk 10325 — MSU Sciences Yearbook Vol. 2, p. 1052
- **Assigned:** `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN APPLIED SCIENCES AND NANOTECHNOLOGY (HNN) > TCNP 201 Technopreneurship`
- **Chunk starts:** design thinking; process thinking, strategic thinking; The NPD process: idea | generation, idea screening, concept testing, market strategy development, business | financial analysis, prototyping, test marketing, commercialization. | Developing and Protecting Intellectual Property: Concept of intellectual property, | Theory behind IP protection, In
- **Preceding short lines:** [10322] Fourier integrals; definition of odd and even functions. Dirac delta-function; Fourier / [10323] Fourier integrals; definition of odd and even functions. Dirac delta-function; Fourier / [10323] Lagrange's Equations including the following: Generalised coordinates and forces, / [10323] Holonomic constraints, The Lagrangian and Lagrange's equations. / [10324] TCNP201 Technopreneurship / [10324] Introduction: Nature and importance of technopreneurship, Differences between / [10324] Small business model and financial issues: Developing a business model, Basics of / [10324] New Product development (NDP): Opportunity recognition and creation, Sources of

### [✓] chunk 10363 — MSU Sciences Yearbook Vol. 2, p. 1060
- **Assigned:** `Section: REGULATIONS FOR BACHELOR OF SCIENCE HONOURS DEGREE IN INDUSTRIAL PHYSICS AND INSTRUMENTATION (HIPI) > 7.0 GENERAL PROVISIONS`
- **Chunk starts:** Departments and to the following conditions: | 7.4.1 The module combination is feasible in terms of timetable, | 7.4.2 A student may apply for exemptions during the first four weeks of the
- **Preceding short lines:** [10361] 9 Demonstrate professional and ethical responsibility / [10361] 10 Apply technopreneurship skills to start new technology-driven businesses / [10361] 11 Apply knowledge and skills to professionally manage projects / [10361] 12 Utilize specialized computational software to analyse and solve problems / [10361] 7.0. GENERAL PROVISIONS / [10362] 7.0. GENERAL PROVISIONS / [10362] Departments and to the following conditions: / [10362] 7.4.1 The module combination is feasible in terms of timetable,

### [✓] chunk 10698 — MSU Sciences Yearbook Vol. 2, p. 1124
- **Assigned:** `Section: REGULATIONS FOR MASTER OF SCIENCE DEGREE IN FOOD SAFETY AND QUALITY MANAGEMENT (MFSQ) > MFSQ 702 Advanced Food Microbiology and Toxicology`
- **Chunk starts:** food irradiation, food intolerance, methylxanthines; use and safety of novel foods. The module further | addresses LD50 calculations and effects of various toxins on the health. | MFSQ 703 Food Safety and Risk Analysis | This module addresses the meaning of food safety and types of hazards in the food chain. It further | provides knowledge on prere
- **Preceding short lines:** [10695] Trade / [10695] MFSQ 806 Food Chemistry / [10695] MFSQ 807 Food Business Operations Management / [10695] Level 2 Semester 2 / [10695] MODULE SYNOPSES / [10696] MODULE SYNOPSES / [10696] MFSQ 701 Total Quality Management / [10697] MFSQ 702 Advanced Food Microbiology and Toxicology
