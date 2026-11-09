"""M0의 역량 질문(CQ)에 대응하는 읽기 전용 Cypher 조회문.

질문 하나당 최대 sample_limit개의 경로·행만 가져오므로 반환 행 수는 전체 건수가 아니다.
모든 조회는 dataset_id로 양 끝 개체 및 모든 관계를 제한한다.
"""

COMPANIES = [
    'COMPANY-AMOREPACIFIC', 'COMPANY-INNISFREE', 'COMPANY-ESPOIR',
    'COMPANY-ETUDE', 'COMPANY-PACIFICTECH', 'COMPANY-AMOSPROFESSIONAL',
    'COMPANY-COSRX',
]
HOLDINGS = 'COMPANY-AMOREPACIFIC-HOLDINGS'
AMOREPACIFIC = 'COMPANY-AMOREPACIFIC'
COSRX = 'COMPANY-COSRX'

# 노드의 추출·정규화 기록 및 관계 전체 속성을 그대로 담아 이후 원문 근거를 확인한다.
# sources_json과 disclosure_notes_json은 관계 속성에 포함된 JSON 문자열이다.
PATH_RESULT = '''
RETURN [n IN nodes(path) | {labels: labels(n), properties: properties(n)}] AS nodes,
       [r IN relationships(path) | {type: type(r), start_id: startNode(r).entity_id, end_id: endNode(r).entity_id, properties: properties(r)}] AS relationships
LIMIT $sample_limit
'''


def path_query(pattern: str, where: str = '') -> str:
    dataset = '''all(n IN nodes(path) WHERE n.dataset_id = $dataset_id)
  AND all(r IN relationships(path) WHERE r.dataset_id = $dataset_id)'''
    if where:
        dataset += '\n  AND ' + where
    return 'MATCH path = ' + pattern + '\nWHERE ' + dataset + '\n' + PATH_RESULT


def get_queries() -> list[dict]:
    """고정 CQ 목록과 기본 파라미터. dataset_id/sample_limit은 실행기가 주입한다."""
    return [
        {
            'id': 'CQ01',
            'question': '조사 대상 7개 기업의 정식 명칭, 업종, 주요 사업은 무엇인가?',
            'cypher': '''MATCH (company:B_Company {dataset_id:$dataset_id})
WHERE company.entity_id IN $company_ids
RETURN {labels: labels(company), properties: properties(company)} AS company
ORDER BY company.entity_id
LIMIT $sample_limit''',
            'parameters': {'company_ids': COMPANIES},
        },
        {
            'id': 'CQ02',
            'question': '조사 대상 7개 기업의 2025년 매출액과 영업이익은 각각 얼마이며, 어떤 재무제표를 근거로 하는가?',
            'cypher': path_query(
                '(company:B_Company)-[metric_relation:B_REPORTS_METRIC]->(metric:B_MetricObservation)',
                "company.entity_id IN $company_ids AND metric.entity_id STARTS WITH 'FINANCIAL-' AND metric.fiscal_year = 2025 "
                "AND metric.name IN ['매출액', '영업이익']"),
            'parameters': {'company_ids': COMPANIES},
        },
        {
            'id': 'CQ03',
            'question': '2026년 3월 31일 기준, 아모레퍼시픽홀딩스가 지분을 보유한 조사 대상 기업과 보고서에 기재된 지분율은 무엇인가?',
            'cypher': path_query(
                '(holding:B_Company)-[ownership:B_OWNS_STAKE]->(company:B_Company)',
                'holding.entity_id = $holdings_id AND company.entity_id IN $company_ids '
                'AND ownership.as_of_date = $as_of_date AND ownership.sources_json CONTAINS $disclosure_marker'),
            'parameters': {'holdings_id': HOLDINGS, 'company_ids': COMPANIES, 'as_of_date': '2026-03-31',
                           'disclosure_marker': '"source_kind":"disclosure"'},
        },
        {
            'id': 'CQ04',
            'question': '2026년 3월 31일 기준, 아모레퍼시픽홀딩스와 코스알엑스는 어떤 기업을 거쳐 지분 관계로 연결되는가?',
            'cypher': path_query(
                '(holding:B_Company)-[ownership1:B_OWNS_STAKE]->(middle:B_Company)'
                '-[ownership2:B_OWNS_STAKE]->(target:B_Company)',
                'holding.entity_id = $holdings_id AND target.entity_id = $cosrx_id '
                'AND ownership1.as_of_date = $as_of_date AND ownership2.as_of_date = $as_of_date '
                "AND coalesce(ownership1.status, '') <> 'planned' AND coalesce(ownership2.status, '') <> 'planned'"),
            'parameters': {'holdings_id': HOLDINGS, 'cosrx_id': COSRX, 'as_of_date': '2026-03-31'},
        },
        {
            'id': 'CQ05',
            'question': '특정 기업의 임직원으로 기사에 등장한 인물은 누구이며, 기사에서 어떤 직책으로 소개됐는가?',
            'cypher': path_query(
                '(person:B_Person)-[role:B_HOLDS_POSITION]->(company:B_Company)',
                'company.entity_id = $company_id'),
            'parameters': {'company_id': AMOREPACIFIC},
        },
        {
            'id': 'CQ06',
            'question': '아모레퍼시픽홀딩스가 지분을 보유한 기업과 관련된 브랜드 및 그 브랜드의 제품은 무엇인가?',
            'cypher': path_query(
                '(holding:B_Company)-[:B_OWNS_STAKE]->(company:B_Company)'
                '-[:B_OPERATES_BRAND]->(brand:B_Brand)<-[:B_PRODUCT_UNDER_BRAND]-(product:B_Product)',
                'holding.entity_id = $holdings_id'),
            'parameters': {'holdings_id': HOLDINGS},
        },
        {
            'id': 'CQ07',
            'question': '아모레퍼시픽홀딩스가 지분을 보유한 기업 중 기사에서 행사에 참여한 기업은 어디이며, 그 행사는 어디에서 열렸는가?',
            'cypher': path_query(
                '(holding:B_Company)-[:B_OWNS_STAKE]->(company:B_Company)'
                '-[:B_PARTICIPATES_IN]->(event:B_Event)-[:B_EVENT_IN_PLACE]->(place:B_Place)',
                'holding.entity_id = $holdings_id'),
            'parameters': {'holdings_id': HOLDINGS},
        },
        {
            'id': 'CQ08',
            'question': '특정 인물이 기사에서 직책을 맡은 기업과 관련된 브랜드 및 그 브랜드의 제품은 무엇인가?',
            'cypher': path_query(
                '(person:B_Person)-[:B_HOLDS_POSITION]->(company:B_Company)'
                '-[:B_OPERATES_BRAND]->(brand:B_Brand)<-[:B_PRODUCT_UNDER_BRAND]-(product:B_Product)',
                'person.name = $person_name'),
            'parameters': {'person_name': '서경배'},
        },
        {
            'id': 'CQ09',
            'question': '아모레퍼시픽홀딩스에서 아모레퍼시픽을 거쳐 연결되는 코스알엑스와 관련된 브랜드 및 제품은 무엇인가?',
            'cypher': path_query(
                '(holding:B_Company)-[:B_OWNS_STAKE]->(amore:B_Company)'
                '-[:B_OWNS_STAKE]->(cosrx:B_Company)-[:B_OPERATES_BRAND]->(brand:B_Brand)'
                '<-[:B_PRODUCT_UNDER_BRAND]-(product:B_Product)',
                'holding.entity_id = $holdings_id AND amore.entity_id = $amore_id '
                'AND cosrx.entity_id = $cosrx_id'),
            'parameters': {'holdings_id': HOLDINGS, 'amore_id': AMOREPACIFIC, 'cosrx_id': COSRX},
        },
        {
            'id': 'CQ10',
            'question': '특정 인물이 지분을 보유한 회사와 지분 관계로 연결된 기업의 브랜드는 어떤 행사에 참여했으며, 그 행사는 어디에서 열렸는가?',
            'cypher': path_query(
                '(person:B_Person)-[:B_OWNS_STAKE]->(company1:B_Company)'
                '-[:B_OWNS_STAKE]->(company2:B_Company)-[:B_OPERATES_BRAND]->(brand:B_Brand)'
                '-[:B_PARTICIPATES_IN]->(event:B_Event)-[:B_EVENT_IN_PLACE]->(place:B_Place)',
                'person.name = $person_name'),
            'parameters': {'person_name': '서경배'},
        },
    ]
