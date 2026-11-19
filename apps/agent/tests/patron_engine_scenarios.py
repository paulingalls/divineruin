from test_dawns_resilience import SCENARIOS as dawns_resilience
from test_patron_engine_aelora import SCENARIOS as aelora
from test_patron_engine_beacon import SCENARIOS as beacon
from test_patron_engine_judgment import SCENARIOS as judgment
from test_patron_engine_kaelen import SCENARIOS as kaelen
from test_patron_engine_nythera import SCENARIOS as nythera
from test_patron_engine_orenthel import SCENARIOS as orenthel
from test_patron_engine_syrath import SCENARIOS as syrath
from test_patron_engine_thyra import SCENARIOS as thyra
from test_patron_passives import SCENARIOS as passives
from test_patron_senses import SCENARIOS as senses
from test_zhael_fate import SCENARIOS as lucky
from test_zhael_fate_callers import SCENARIOS as zhael

ENGINE_SCENARIOS = {
    **aelora,
    **beacon,
    **dawns_resilience,
    **judgment,
    **kaelen,
    **nythera,
    **orenthel,
    **syrath,
    **thyra,
    **zhael,
    **lucky,
    **passives,
    **senses,
}
