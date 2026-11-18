from test_patron_engine_aelora import SCENARIOS as aelora
from test_patron_engine_kaelen import SCENARIOS as kaelen
from test_patron_engine_nythera import SCENARIOS as nythera
from test_patron_engine_syrath import SCENARIOS as syrath
from test_patron_engine_thyra import SCENARIOS as thyra
from test_patron_passives import SCENARIOS as passives
from test_patron_senses import SCENARIOS as senses
from test_zhael_fate import SCENARIOS as lucky
from test_zhael_fate_callers import SCENARIOS as zhael

ENGINE_SCENARIOS = {**aelora, **kaelen, **nythera, **syrath, **thyra, **zhael, **lucky, **passives, **senses}
