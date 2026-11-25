from combat.test_synergy_crit_edges import SCENARIOS as crit_edges
from combat.test_synergy_spell_edges import SCENARIOS as spell_edges
from combat.test_synergy_weapon_damage import SCENARIOS as weapon_damage
from test_dawns_resilience import SCENARIOS as dawns_resilience
from test_encounter_facts_damage import SCENARIOS as encounter_facts
from test_encounter_facts_defense import SCENARIOS as defense
from test_encounter_facts_heal import SCENARIOS as appointed_mercy
from test_encounter_facts_outnumbered import SCENARIOS as outnumbered
from test_encounter_facts_renewal import SCENARIOS as renewal
from test_fallen_ally_guard import SCENARIOS as fallen_ally_guard
from test_heal_synergies import SCENARIOS as dawns_mercy
from test_heal_synergies_place import SCENARIOS as place_healing
from test_kaelen_war_songs import SCENARIOS as war_songs
from test_marshal_death_save import SCENARIOS as marshal_death_save
from test_patron_engine_aelora import SCENARIOS as aelora
from test_patron_engine_aelora_shield import SCENARIOS as aelora_shield
from test_patron_engine_beacon import SCENARIOS as beacon
from test_patron_engine_dawns_embrace import SCENARIOS as dawns_embrace
from test_patron_engine_death_ward import SCENARIOS as death_ward
from test_patron_engine_judgment import SCENARIOS as judgment
from test_patron_engine_kaelen import SCENARIOS as kaelen
from test_patron_engine_mortaen import SCENARIOS as mortaen
from test_patron_engine_nythera import SCENARIOS as nythera
from test_patron_engine_orenthel import SCENARIOS as orenthel
from test_patron_engine_syrath import SCENARIOS as syrath
from test_patron_engine_thyra import SCENARIOS as thyra
from test_patron_engine_thyra_wrath import SCENARIOS as thyra_wrath
from test_patron_engine_valdris import SCENARIOS as valdris
from test_patron_passives import SCENARIOS as passives
from test_patron_senses import SCENARIOS as senses
from test_zhael_fate import SCENARIOS as lucky
from test_zhael_fate_callers import SCENARIOS as zhael

ENGINE_SCENARIOS = {
    **valdris,
    **aelora,
    **aelora_shield,
    **beacon,
    **dawns_mercy,
    **place_healing,
    **dawns_resilience,
    **crit_edges,
    **encounter_facts,
    **defense,
    **fallen_ally_guard,
    **marshal_death_save,
    **war_songs,
    **appointed_mercy,
    **renewal,
    **outnumbered,
    **judgment,
    **kaelen,
    **mortaen,
    **death_ward,
    **dawns_embrace,
    **nythera,
    **orenthel,
    **syrath,
    **thyra,
    **thyra_wrath,
    **zhael,
    **lucky,
    **passives,
    **senses,
    **spell_edges,
    **weapon_damage,
}
