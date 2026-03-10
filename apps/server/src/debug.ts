import { getRoomService, DataPacket_Kind } from "./livekit.ts";

export async function handleDebugRooms(): Promise<Response> {
  const roomService = getRoomService();
  if (!roomService) {
    return Response.json({ error: "LiveKit is not configured" }, { status: 503 });
  }
  try {
    const rooms = await roomService.listRooms();
    const list = rooms.map((r) => ({
      name: r.name,
      numParticipants: r.numParticipants,
      creationTime: Number(r.creationTime),
    }));
    return Response.json(list);
  } catch {
    return Response.json({ error: "Failed to list rooms" }, { status: 500 });
  }
}

export async function handleDebugSendEvent(req: Request): Promise<Response> {
  const roomService = getRoomService();
  if (!roomService) {
    return Response.json({ error: "LiveKit is not configured" }, { status: 503 });
  }
  const body = (await req.json()) as { room?: string; event?: { type?: string } };
  if (!body.room) {
    return Response.json({ error: "room is required" }, { status: 400 });
  }
  if (!body.event?.type) {
    return Response.json({ error: "event.type is required" }, { status: 400 });
  }

  try {
    const data = new TextEncoder().encode(JSON.stringify(body.event));
    await roomService.sendData(body.room, data, DataPacket_Kind.RELIABLE, {
      topic: "game_events",
    });
    return Response.json({ ok: true, type: body.event.type, room: body.room });
  } catch {
    return Response.json({ error: "Failed to send event" }, { status: 500 });
  }
}

export function handleDebugPage(): Response {
  return new Response(DEBUG_HTML, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Content-Security-Policy":
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'",
    },
  });
}

const DEBUG_HTML = /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Divine Ruin — Debug Event Console</title>
<style>
  :root {
    --void: #0A0A0B;
    --ink: #141416;
    --charcoal: #1E1E22;
    --slate: #2A2A30;
    --ash: #6B6B75;
    --bone: #D4D0C8;
    --parchment: #E8E4DA;
    --hollow: #2DD4BF;
    --ember: #C2410C;
    --gold: #C9A84C;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    background: var(--void);
    color: var(--bone);
    padding: 16px;
    min-height: 100vh;
  }
  h1 { font-size: 16px; color: var(--hollow); margin-bottom: 12px; letter-spacing: 1px; }
  h2 { font-size: 12px; color: var(--ash); text-transform: uppercase; letter-spacing: 2px; margin: 16px 0 8px; }
  h3 { font-size: 11px; color: var(--gold); text-transform: uppercase; letter-spacing: 1px; margin: 8px 0 4px; }

  .header {
    display: flex; align-items: center; gap: 8px; margin-bottom: 16px;
    padding: 10px 12px; background: var(--ink); border: 1px solid var(--slate); border-radius: 6px;
  }
  .header label { font-size: 11px; color: var(--ash); text-transform: uppercase; letter-spacing: 1px; }
  select {
    background: var(--charcoal); color: var(--bone); border: 1px solid var(--slate);
    padding: 6px 10px; border-radius: 4px; font-family: inherit; font-size: 13px; flex: 1;
  }
  .status { font-size: 11px; padding: 4px 8px; border-radius: 4px; }
  .status.ok { color: var(--hollow); background: rgba(45,212,191,0.1); }
  .status.err { color: var(--ember); background: rgba(194,65,12,0.1); }

  .nav {
    position: sticky; top: 0; z-index: 10;
    display: flex; flex-wrap: wrap; gap: 4px;
    padding: 8px 10px; margin-bottom: 12px;
    background: var(--ink); border: 1px solid var(--slate); border-radius: 6px;
  }
  .nav a {
    color: var(--ash); font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
    text-decoration: none; padding: 3px 6px; border-radius: 3px;
    transition: color 0.15s, background 0.15s;
  }
  .nav a:hover { color: var(--hollow); background: var(--charcoal); }

  .btn {
    background: var(--charcoal); color: var(--bone); border: 1px solid var(--slate);
    padding: 6px 12px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 12px;
    transition: border-color 0.15s, background 0.15s;
  }
  .btn:hover { border-color: var(--hollow); background: var(--slate); }
  .btn:active { background: var(--hollow); color: var(--void); }
  .btn.small { padding: 4px 8px; font-size: 11px; }
  .btn.active { border-color: var(--hollow); background: var(--hollow); color: var(--void); }

  .grid {
    display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px;
  }

  .section { margin-bottom: 12px; padding: 10px; background: var(--ink); border: 1px solid var(--charcoal); border-radius: 6px; }

  .custom-area {
    display: flex; gap: 8px; align-items: flex-start;
  }
  textarea {
    background: var(--charcoal); color: var(--parchment); border: 1px solid var(--slate);
    border-radius: 4px; font-family: inherit; font-size: 12px; padding: 8px;
    width: 100%; min-height: 100px; resize: vertical;
  }

  #log {
    background: var(--ink); border: 1px solid var(--charcoal); border-radius: 6px;
    padding: 8px; max-height: 200px; overflow-y: auto; font-size: 11px;
  }
  .log-entry { padding: 3px 0; border-bottom: 1px solid var(--charcoal); display: flex; gap: 8px; }
  .log-time { color: var(--ash); min-width: 60px; }
  .log-type { color: var(--hollow); min-width: 140px; }
  .log-room { color: var(--ash); min-width: 100px; }
  .log-ok { color: var(--hollow); }
  .log-err { color: var(--ember); }
</style>
</head>
<body>
<h1>DIVINE RUIN — DEBUG EVENT CONSOLE</h1>

<div class="header">
  <label>Room</label>
  <select id="rooms"><option value="">Loading…</option></select>
  <button class="btn" onclick="refreshRooms()">Refresh</button>
  <span id="status" class="status"></span>
</div>

<nav class="nav">
  <a href="#sec-session">Session</a>
  <a href="#sec-creation">Creation</a>
  <a href="#sec-combat">Combat</a>
  <a href="#sec-items">Items</a>
  <a href="#sec-inventory">Inventory</a>
  <a href="#sec-quest">Quest</a>
  <a href="#sec-location">Location</a>
  <a href="#sec-portraits">Portraits</a>
  <a href="#sec-status">Status</a>
  <a href="#sec-divine">Divine</a>
  <a href="#sec-music">Music</a>
  <a href="#sec-sound">Sound</a>
  <a href="#sec-transcript">Transcript</a>
  <a href="#sec-narration">Narration</a>
  <a href="#sec-custom">Custom</a>
</nav>

<div class="section" id="sec-session">
  <h2>Session Lifecycle</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'session_init',character:{name:'Kael',race:'Human',class:'Warden',level:3,xp:450,hp:{current:24,max:30},attributes:{strength:14,dexterity:12,constitution:13,intelligence:10,wisdom:15,charisma:8},ac:16,proficiencies:['athletics','perception','survival'],equipment:{main_hand:{name:'Iron Longsword',damage:'1d8+2'},armor:{name:'Chain Mail',ac:16},shield:null},gold:47,divine_favor:{patron:'Solwyn',level:12,max:100}},location:{id:'accord_market_square',name:'Market Square',atmosphere:'Bustling stalls and the smell of fresh bread.',region:'Accord of Tides',tags:['urban','market','busy'],ambient_sounds:'market_bustle',exits:{north:{destination:'accord_guild_hall'},south:{destination:'accord_dockside'},east:{destination:'accord_temple_row'}}},world_state:{time:'day',day:14,season:'spring'},portraits:{companion:{primary:'/api/assets/images/placeholder',alert:'/api/assets/images/placeholder'},npcs:{'Maren the Innkeeper':'/api/assets/images/placeholder','Torin':'/api/assets/images/placeholder','Emris':'/api/assets/images/placeholder','Grimjaw':'/api/assets/images/placeholder'}},inventory:[{id:'item_1',name:'Iron Longsword',type:'weapon',rarity:'common',description:'A sturdy blade.',weight:3,effects:[],lore:'',value_base:15,slot_info:{quantity:1,equipped:true}},{id:'item_2',name:'Healing Potion',type:'consumable',rarity:'uncommon',description:'Restores 2d4+2 HP.',weight:0.5,effects:[{heal:'2d4+2'}],lore:'',value_base:50,slot_info:{quantity:2,equipped:false},image_url:'/api/assets/images/placeholder'},{id:'item_3',name:'Hollow-Touched Compass',type:'trinket',rarity:'rare',description:'The needle drifts toward corruption.',weight:0.1,effects:[],lore:'Found in the old mill ruins.',value_base:120,slot_info:{quantity:1,equipped:false},image_url:'/api/assets/images/placeholder'}],quests:[{quest_id:'q_greyvale_anomaly',quest_name:'The Greyvale Anomaly',type:'main',current_stage:1,stages:[{id:'s0',name:'Discovery',objective:'Investigate the strange lights near the old mill.'},{id:'s1',name:'The Source',objective:'Find the source of corruption in the mill basement.'},{id:'s2',name:'Confrontation',objective:'Defeat or seal the Hollow rift.'}]}],map_progress:[{location_id:'accord_market_square',connections:['accord_guild_hall','accord_dockside','accord_temple_row']},{location_id:'accord_hearthstone_tavern',connections:['accord_dockside','accord_market_square']}]})">Session Init (Full)</button>
    <button class="btn" onclick="send({type:'session_end',summary:'You defended the market from a goblin raid and discovered a lead on the Hollow rift beneath the old mill. Maren the Innkeeper offered shelter and information.',xp_earned:175,items_found:['Hollow-Touched Compass','Healing Potion'],quest_progress:['The Greyvale Anomaly: advanced to The Source'],duration:2700,next_hooks:['The mill basement awaits','Maren mentioned a missing merchant'],story_moments:[{moment_key:'goblin_raid_defense',description:'You held the market square against a goblin raid, rallying the merchants to safety.',image_url:'/api/assets/images/placeholder'},{moment_key:'hollow_compass_discovery',description:'In the wreckage, you found a compass whose needle points toward corruption.',image_url:'/api/assets/images/placeholder'},{moment_key:'maren_alliance',description:'Maren the Innkeeper offered shelter and shared what she knows of the missing merchant.'}]})">Session End (Summary)</button>
    <button class="btn" onclick="send({type:'session_end'})">Session End (No Summary)</button>
  </div>
</div>

<div class="section" id="sec-creation">
  <h2>Character Creation</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'creation_cards',cards:[{id:'race_human',title:'Human',subtitle:'Versatile and ambitious',description:'Humans adapt to any situation. +1 to all attributes.',image_hint:'human_portrait',image_url:'/api/assets/images/placeholder'},{id:'race_elf',title:'Elf',subtitle:'Ancient and perceptive',description:'Elves possess keen senses and a deep connection to nature. +2 Dexterity, +1 Wisdom.',image_hint:'elf_portrait',image_url:'/api/assets/images/placeholder'},{id:'race_dwarf',title:'Dwarf',subtitle:'Stout and resilient',description:'Dwarves are tough and steadfast. +2 Constitution, +1 Strength.',image_hint:'dwarf_portrait',image_url:'/api/assets/images/placeholder'},{id:'race_halfling',title:'Halfling',subtitle:'Lucky and nimble',description:'Halflings are quick on their feet and hard to hit. +2 Dexterity, +1 Charisma.',image_hint:'halfling_portrait',image_url:'/api/assets/images/placeholder'}]})">Race Cards (with art)</button>
    <button class="btn" onclick="send({type:'creation_cards',cards:[{id:'class_warden',title:'Warden',subtitle:'Guardian of the wild',description:'Wardens blend martial skill with nature magic. Heavy armor, melee focus, healing prayers.',image_url:'/api/assets/images/placeholder'},{id:'class_shadowbind',title:'Shadowbind',subtitle:'Master of stealth',description:'Shadowbinds strike from darkness. Light armor, dual wield, evasion, critical hits.',image_url:'/api/assets/images/placeholder'},{id:'class_faithsworn',title:'Faithsworn',subtitle:'Divine champion',description:'Faithsworn channel their deity. Medium armor, divine spells, turn undead, smite.',image_url:'/api/assets/images/placeholder'}]})">Class Cards (with art)</button>
    <button class="btn" onclick="send({type:'creation_card_selected',value:'race_human'})">Select Card (Human)</button>
    <button class="btn" onclick="send({type:'creation_card_selected',value:'class_warden'})">Select Card (Warden)</button>
  </div>
</div>

<div class="section" id="sec-combat">
  <h2>Dice &amp; Combat</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'dice_result',roll:14,modifier:2,total:16,success:true,roll_type:'skill_check',narrative:'The lock clicks open beneath your nimble fingers.'})">Skill Check Success</button>
    <button class="btn" onclick="send({type:'dice_result',roll:3,modifier:2,total:5,success:false,roll_type:'skill_check',narrative:'The mechanism jams — your pick snaps inside the lock.'})">Skill Check Failure</button>
    <button class="btn" onclick="send({type:'dice_result',roll:20,modifier:4,total:24,success:true,roll_type:'attack',narrative:'A devastating blow! The blade finds the gap in its armor.'})">Critical Hit (Nat 20)</button>
    <button class="btn" onclick="send({type:'combat_started',difficulty:'moderate'})">Combat Start (Moderate)</button>
    <button class="btn" onclick="send({type:'combat_started',difficulty:'hard'})">Combat Start (Hard)</button>
    <button class="btn" onclick="send({type:'combat_ui_update',phase:'player_turn',round:2,combatants:[{id:'c1',name:'Kael',isAlly:true,hpCurrent:24,hpMax:30,statusEffects:[],isActive:true},{id:'c2',name:'Goblin Scout',isAlly:false,hpCurrent:8,hpMax:12,statusEffects:[],isActive:false},{id:'c3',name:'Goblin Shaman',isAlly:false,hpCurrent:15,hpMax:18,statusEffects:['shield'],isActive:false}]})">Combat UI Update</button>
    <button class="btn" onclick="send({type:'combat_ended'})">Combat End (Victory)</button>
  </div>
</div>

<div class="section" id="sec-items">
  <h2>Items &amp; Rewards</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'item_acquired',name:'Rusty Dagger',description:'A pitted blade, barely holding its edge.',rarity:'common',stats:{damage:'1d4'}})">Common Item (no art)</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Hollow-Touched Compass',description:'The needle drifts toward sources of corruption.',rarity:'uncommon',stats:{corruption_sense:true},image_url:'/api/assets/images/placeholder'})">Uncommon Item (with art)</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Veilglass Amulet',description:'A shard of crystallized boundary between worlds.',rarity:'rare',stats:{resist_hollow:'+2',perception:'+1'},image_url:'/api/assets/images/placeholder'})">Rare Item (with art)</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Sundered Edge of Kaelthos',description:'A fragment of a god-forged blade, thrumming with divine wrath.',rarity:'legendary',stats:{damage:'2d8+3',divine_smite:true},image_url:'/api/assets/images/placeholder'})">Legendary Item (with art)</button>
    <button class="btn" onclick="send({type:'xp_awarded',new_xp:325,new_level:4,xp_gained:75,level_up:false})">XP +75 (no level-up)</button>
    <button class="btn" onclick="send({type:'xp_awarded',new_xp:1000,new_level:5,xp_gained:250,level_up:true})">Level Up! (xp +250, level 5)</button>
  </div>
</div>

<div class="section" id="sec-inventory">
  <h2>Inventory Sync</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'inventory_updated',inventory:[{id:'item_1',name:'Iron Longsword',type:'weapon',rarity:'common',description:'A sturdy blade.',weight:3,effects:[],lore:'',value_base:15,slot_info:{quantity:1,equipped:true}},{id:'item_2',name:'Healing Potion',type:'consumable',rarity:'uncommon',description:'Restores 2d4+2 HP.',weight:0.5,effects:[{heal:'2d4+2'}],lore:'',value_base:50,slot_info:{quantity:2,equipped:false},image_url:'/api/assets/images/placeholder'},{id:'item_3',name:'Hollow-Touched Compass',type:'trinket',rarity:'rare',description:'The needle drifts toward corruption.',weight:0.1,effects:[],lore:'Found in the old mill ruins.',value_base:120,slot_info:{quantity:1,equipped:false},image_url:'/api/assets/images/placeholder'}]})">Full Inventory (with art)</button>
    <button class="btn" onclick="send({type:'inventory_updated',inventory:[]})">Empty Inventory</button>
  </div>
</div>

<div class="section" id="sec-quest">
  <h2>Quest</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'quest_update',quest_name:'The Greyvale Anomaly',objective:'Investigate the strange lights near the old mill.',status:'active',stage_name:'Discovery'})">Quest Update</button>
    <button class="btn" onclick="send({type:'quest_update',quest_name:'The Greyvale Anomaly',quest_id:'q_greyvale_anomaly',objective:'Find the source of corruption in the mill basement.',status:'active',stage_name:'The Source',new_stage:1})">Quest Advance (stage 1)</button>
    <button class="btn" onclick="send({type:'quest_update',quest_name:'The Greyvale Anomaly',quest_id:'q_greyvale_anomaly',objective:'Defeat or seal the Hollow rift.',status:'active',stage_name:'Confrontation',new_stage:2})">Quest Advance (stage 2)</button>
  </div>
</div>

<div class="section" id="sec-location">
  <h2>Location</h2>
  <h3>Time of Day</h3>
  <div class="grid">
    <button class="btn small active" id="tod-day" onclick="setTimeOfDay('day')">day</button>
    <button class="btn small" id="tod-dusk" onclick="setTimeOfDay('dusk')">dusk</button>
    <button class="btn small" id="tod-night" onclick="setTimeOfDay('night')">night</button>
    <button class="btn small" id="tod-dawn" onclick="setTimeOfDay('dawn')">dawn</button>
  </div>
  <h3>Town</h3>
  <div class="grid">
    <button class="btn small" onclick="sendLocation({id:'accord_market_square',name:'Market Square',atmosphere:'Bustling stalls and the smell of fresh bread.',region:'Accord of Tides',ambient:'market_bustle',connections:['accord_guild_hall','accord_temple_row','accord_dockside']})">accord_market_square</button>
    <button class="btn small" onclick="sendLocation({id:'accord_guild_hall',name:'Guild Hall',atmosphere:'Polished stone and the murmur of adventurers planning their next expedition.',region:'Accord of Tides',ambient:'guild_hall_bustle',connections:['accord_market_square','accord_temple_row']})">accord_guild_hall</button>
    <button class="btn small" onclick="sendLocation({id:'accord_temple_row',name:'Temple Row',atmosphere:'Incense smoke drifts between carved pillars as quiet prayers echo.',region:'Accord of Tides',ambient:'temple_row_chanting',connections:['accord_market_square','accord_guild_hall']})">accord_temple_row</button>
    <button class="btn small" onclick="sendLocation({id:'accord_dockside',name:'Dockside',atmosphere:'Salt wind and creaking ropes. Gulls cry overhead.',region:'Accord of Tides',ambient:'harbor_activity',connections:['accord_market_square','accord_hearthstone_tavern']})">accord_dockside</button>
    <button class="btn small" onclick="sendLocation({id:'millhaven',name:'Millhaven',atmosphere:'A quiet farming village at the edge of Greyvale.',region:'Greyvale',ambient:'rural_town_uneasy',connections:['greyvale_south_road','millhaven_inn','yanna_farmhouse']})">millhaven</button>
  </div>
  <h3>Interior</h3>
  <div class="grid">
    <button class="btn small" onclick="sendLocation({id:'accord_hearthstone_tavern',name:'Hearthstone Tavern',atmosphere:'Warm hearth, low murmur of conversation, tankards on oak.',region:'Accord of Tides',ambient:'tavern_busy',connections:['accord_dockside','accord_market_square']})">accord_hearthstone_tavern</button>
    <button class="btn small" onclick="sendLocation({id:'accord_forge',name:'The Forge',atmosphere:'The clang of hammer on anvil and the heat of the furnace.',region:'Accord of Tides',ambient:'guild_hall_bustle',connections:['accord_market_square']})">accord_forge</button>
    <button class="btn small" onclick="sendLocation({id:'torin_quarters',name:'Torin Quarters',atmosphere:'A tidy room with maps pinned to every wall.',region:'Accord of Tides',ambient:'tavern_busy',connections:['accord_guild_hall']})">torin_quarters</button>
    <button class="btn small" onclick="sendLocation({id:'emris_study',name:'Emris Study',atmosphere:'Dusty tomes and the faint hum of arcane wards.',region:'Accord of Tides',ambient:'temple_row_chanting',connections:['accord_temple_row']})">emris_study</button>
    <button class="btn small" onclick="sendLocation({id:'grimjaw_quarters',name:'Grimjaw Quarters',atmosphere:'A spartan room smelling of weapon oil and old leather.',region:'Accord of Tides',ambient:'dungeon_ancient_hum',connections:['accord_guild_hall']})">grimjaw_quarters</button>
    <button class="btn small" onclick="sendLocation({id:'millhaven_inn',name:'Millhaven Inn',atmosphere:'Creaking floorboards and the smell of stew simmering.',region:'Greyvale',ambient:'tavern_busy',connections:['millhaven']})">millhaven_inn</button>
    <button class="btn small" onclick="sendLocation({id:'yanna_farmhouse',name:'Yanna Farmhouse',atmosphere:'Dried herbs hang from the rafters. A cat watches from the hearth.',region:'Greyvale',ambient:'rural_town_uneasy',connections:['millhaven']})">yanna_farmhouse</button>
  </div>
  <h3>Wilderness</h3>
  <div class="grid">
    <button class="btn small" onclick="sendLocation({id:'greyvale_south_road',name:'South Road',atmosphere:'A rutted dirt road winding through fallow fields.',region:'Greyvale',ambient:'rural_town_uneasy',connections:['millhaven','greyvale_ruins_exterior']})">greyvale_south_road</button>
    <button class="btn small" onclick="sendLocation({id:'greyvale_wilderness_north',name:'Northern Wilds',atmosphere:'Dense undergrowth and the distant call of wolves.',region:'Greyvale',ambient:'wind_ruins',connections:['greyvale_south_road']})">greyvale_wilderness_north</button>
    <button class="btn small" onclick="sendLocation({id:'greyvale_ruins_exterior',name:'Ruins Exterior',atmosphere:'Crumbling stone walls choked with ivy. Something feels wrong.',region:'Greyvale',ambient:'wind_ruins',connections:['greyvale_south_road','greyvale_ruins_entrance']})">greyvale_ruins_exterior</button>
  </div>
  <h3>Corrupted</h3>
  <div class="grid">
    <button class="btn small" onclick="sendLocation({id:'greyvale_ruins_entrance',name:'Ruins Entrance',atmosphere:'A dark archway. The air tastes of copper and ozone.',region:'Greyvale',ambient:'dungeon_ancient_hum',connections:['greyvale_ruins_exterior','greyvale_ruins_inner']})">greyvale_ruins_entrance</button>
    <button class="btn small" onclick="sendLocation({id:'greyvale_ruins_inner',name:'Ruins Inner Sanctum',atmosphere:'The walls pulse with a faint, sickly light. Reality feels thin.',region:'Greyvale',ambient:'dungeon_resonance_deep',connections:['greyvale_ruins_entrance','hollow_incursion_site']})">greyvale_ruins_inner</button>
    <button class="btn small" onclick="sendLocation({id:'hollow_incursion_site',name:'Hollow Incursion Site',atmosphere:'The boundary has broken. Twisted geometries and whispering void.',region:'Greyvale',ambient:'hollow_wrongness',connections:['greyvale_ruins_inner']})">hollow_incursion_site</button>
  </div>
  <h3>Soundscape Override</h3>
  <div class="grid">
    <button class="btn small" onclick="sendSoundscapeOverride('market_bustle')">market_bustle</button>
    <button class="btn small" onclick="sendSoundscapeOverride('harbor_quiet')">harbor_quiet</button>
    <button class="btn small" onclick="sendSoundscapeOverride('rural_town_uneasy')">rural_town_uneasy</button>
    <button class="btn small" onclick="sendSoundscapeOverride('dungeon_ancient_hum')">dungeon_ancient_hum</button>
    <button class="btn small" onclick="sendSoundscapeOverride('hollow_wrongness')">hollow_wrongness</button>
    <button class="btn small" onclick="sendSoundscapeOverride('guild_hall_bustle')">guild_hall_bustle</button>
    <button class="btn small" onclick="sendSoundscapeOverride('temple_row_chanting')">temple_row_chanting</button>
    <button class="btn small" onclick="sendSoundscapeOverride('harbor_activity')">harbor_activity</button>
    <button class="btn small" onclick="sendSoundscapeOverride('tavern_busy')">tavern_busy</button>
    <button class="btn small" onclick="sendSoundscapeOverride('wind_ruins')">wind_ruins</button>
    <button class="btn small" onclick="sendSoundscapeOverride('dungeon_resonance_deep')">dungeon_resonance_deep</button>
  </div>
</div>

<div class="section" id="sec-portraits">
  <h2>Portraits</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'session_init',portraits:{companion:{primary:'/api/assets/images/placeholder',alert:'/api/assets/images/placeholder'},npcs:{'Maren the Innkeeper':'/api/assets/images/placeholder','Torin':'/api/assets/images/placeholder','Emris':'/api/assets/images/placeholder','Grimjaw':'/api/assets/images/placeholder','Yanna':'/api/assets/images/placeholder'}}})">Setup NPC Portrait Map</button>
    <button class="btn" onclick="send({type:'player_portrait_ready',url:'/api/assets/images/placeholder'})">Player Portrait Ready</button>
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'npc',character:'Maren the Innkeeper',emotion:'warm',text:'Your usual table is free, traveler.',timestamp:Date.now()/1000})">NPC Transcript (Maren)</button>
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'npc',character:'Torin',emotion:'serious',text:'We need to move before nightfall.',timestamp:Date.now()/1000})">NPC Transcript (Torin)</button>
  </div>
</div>

<div class="section" id="sec-status">
  <h2>Status &amp; HP</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'status_effect',action:'add',effect_id:'blessed_1',name:'Blessed',category:'buff'})">Add Buff (Blessed)</button>
    <button class="btn" onclick="send({type:'status_effect',action:'add',effect_id:'poisoned_1',name:'Poisoned',category:'debuff'})">Add Debuff (Poisoned)</button>
    <button class="btn" onclick="send({type:'status_effect',action:'remove',effect_id:'blessed_1',name:'Blessed',category:'buff'})">Remove Effect (Blessed)</button>
    <button class="btn" onclick="send({type:'hp_changed',current:15,max:30})">Take Damage (HP 15/30)</button>
    <button class="btn" onclick="send({type:'hp_changed',current:5,max:30})">Critical HP (HP 5/30)</button>
    <button class="btn" onclick="send({type:'hp_changed',current:28,max:30})">Heal (HP 28/30)</button>
  </div>
</div>

<div class="section" id="sec-divine">
  <h2>Divine &amp; Corruption</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'divine_favor_changed',amount:10,patron_id:'solwyn',new_level:22,max:100})">Divine Favor +10 (Solwyn)</button>
    <button class="btn" onclick="send({type:'divine_favor_changed',amount:25,patron_id:'kaelthos',new_level:50,max:100})">Divine Favor +25 (Kaelthos)</button>
    <button class="btn" onclick="send({type:'divine_favor_changed',amount:0,patron_id:'solwyn',new_level:5,max:100})">Divine Favor Lost</button>
    <button class="btn small" onclick="send({type:'hollow_corruption_changed',level:0})">Corruption 0 (Clean)</button>
    <button class="btn small" onclick="send({type:'hollow_corruption_changed',level:1})">Corruption 1 (Touched)</button>
    <button class="btn small" onclick="send({type:'hollow_corruption_changed',level:2})">Corruption 2 (Tainted)</button>
    <button class="btn small" onclick="send({type:'hollow_corruption_changed',level:3})">Corruption 3 (Consumed)</button>
  </div>
</div>

<div class="section" id="sec-music">
  <h2>Music</h2>
  <div class="grid">
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'exploration'})">exploration</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'tension'})">tension</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'combat_standard'})">combat_standard</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'combat_boss'})">combat_boss</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'wonder'})">wonder</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'sorrow'})">sorrow</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'hollow_dissolution'})">hollow_dissolution</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'silence'})">silence</button>
    <button class="btn small" onclick="send({type:'set_music_state',music_state:'title'})">title</button>
  </div>
</div>

<div class="section" id="sec-sound">
  <h2>Sound Effects</h2>
  <div class="grid">
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'dice_roll'})">dice_roll</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'sword_clash'})">sword_clash</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'tavern'})">tavern</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'quest_sting'})">quest_sting</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'level_up_sting'})">level_up_sting</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'item_pickup'})">item_pickup</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'notification'})">notification</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'success_sting'})">success_sting</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'fail_sting'})">fail_sting</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'menu_open'})">menu_open</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'menu_close'})">menu_close</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'spell_cast'})">spell_cast</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'arrow_loose'})">arrow_loose</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'hit_taken'})">hit_taken</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'critical_hit_sting'})">critical_hit_sting</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'shield_block'})">shield_block</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'potion_use'})">potion_use</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'door_creak'})">door_creak</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'discovery_chime'})">discovery_chime</button>
    <button class="btn small" onclick="send({type:'play_sound',sound_name:'god_whisper_stinger'})">god_whisper_stinger</button>
  </div>
</div>

<div class="section" id="sec-transcript">
  <h2>Transcript</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'dm',text:'The cobblestones glisten with rain as you step into the market square. The scent of wet wool and roasting meat hangs in the air.',timestamp:Date.now()/1000})">DM Narration</button>
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'npc',character:'Maren the Innkeeper',emotion:'warm',text:'Welcome back, traveler. Your usual table is free — and I have news about that merchant you were asking after.',timestamp:Date.now()/1000})">NPC Dialogue</button>
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'player',character:'Kael',text:'I want to check the old mill before nightfall.',timestamp:Date.now()/1000})">Player Speech</button>
    <button class="btn" onclick="send({type:'transcript_entry',speaker:'tool',text:'Perception check: rolled 14 + 3 (modifier) = 17. Success — you notice faint scratch marks on the cellar door.',timestamp:Date.now()/1000})">Tool Result</button>
  </div>
</div>

<div class="section" id="sec-narration">
  <h2>Narration</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'play_narration',url:'/api/audio/narration/sample_001.mp3'})">Play Narration (sample)</button>
    <button class="btn" onclick="send({type:'play_narration',url:'/api/audio/narration/intro.mp3'})">Play Narration (intro)</button>
  </div>
</div>

<div class="section" id="sec-custom">
  <h2>Custom Event</h2>
  <div class="custom-area">
    <textarea id="custom">{ "type": "dice_result", "roll": 17, "modifier": 3, "total": 20, "success": true, "roll_type": "attack", "narrative": "Your arrow finds its mark." }</textarea>
    <button class="btn" onclick="sendCustom()">Send</button>
  </div>
</div>

<h2>Event Log</h2>
<div id="log"></div>

<script>
const roomSel = document.getElementById('rooms');
const statusEl = document.getElementById('status');
const logEl = document.getElementById('log');

let currentTimeOfDay = 'day';
let lastLocation = {id: 'accord_market_square', name: 'Market Square', atmosphere: '', region: '', connections: []};

function setStatus(text, ok) {
  statusEl.textContent = text;
  statusEl.className = 'status ' + (ok ? 'ok' : 'err');
}

function setTimeOfDay(tod) {
  currentTimeOfDay = tod;
  document.querySelectorAll('#sec-location .grid:first-of-type .btn').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('tod-' + tod).classList.add('active');
}

function sendLocation(loc) {
  lastLocation = loc;
  send({
    type: 'location_changed',
    new_location: loc.id,
    location_name: loc.name,
    atmosphere: loc.atmosphere,
    region: loc.region,
    ambient_sounds: loc.ambient,
    time_of_day: currentTimeOfDay,
    connections: loc.connections
  });
}

function sendSoundscapeOverride(soundscape) {
  send({
    type: 'location_changed',
    new_location: lastLocation.id,
    location_name: lastLocation.name,
    atmosphere: lastLocation.atmosphere,
    region: lastLocation.region,
    ambient_sounds: soundscape,
    time_of_day: currentTimeOfDay,
    connections: lastLocation.connections
  });
}

async function refreshRooms() {
  try {
    const res = await fetch('/api/debug/rooms');
    if (!res.ok) { setStatus('Error ' + res.status, false); return; }
    const rooms = await res.json();
    roomSel.innerHTML = '';
    if (rooms.length === 0) {
      roomSel.innerHTML = '<option value="">No rooms</option>';
      setStatus('No rooms', false);
    } else {
      rooms.forEach(function(r) {
        const opt = document.createElement('option');
        opt.value = r.name;
        opt.textContent = r.name + ' (' + r.numParticipants + ' participants)';
        roomSel.appendChild(opt);
      });
      setStatus(rooms.length + ' room(s)', true);
    }
  } catch (e) {
    setStatus('Fetch failed', false);
  }
}

async function send(event) {
  const room = roomSel.value;
  if (!room) { logEntry(event.type, '-', 'No room selected', false); return; }
  try {
    const res = await fetch('/api/debug/event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room: room, event: event }),
    });
    const data = await res.json();
    if (res.ok) {
      logEntry(event.type, room, 'OK', true);
    } else {
      logEntry(event.type, room, data.error || 'Error ' + res.status, false);
    }
  } catch (e) {
    logEntry(event.type, room, e.message, false);
  }
}

function sendCustom() {
  try {
    const event = JSON.parse(document.getElementById('custom').value);
    send(event);
  } catch (e) {
    logEntry('custom', '-', 'Invalid JSON: ' + e.message, false);
  }
}

function logEntry(type, room, msg, ok) {
  const now = new Date();
  const ts = now.toLocaleTimeString('en-US', { hour12: false });
  const div = document.createElement('div');
  div.className = 'log-entry';

  const span = (cls, text) => {
    const s = document.createElement('span');
    s.className = cls;
    s.textContent = text;
    return s;
  };

  div.appendChild(span('log-time', ts));
  div.appendChild(span('log-type', type));
  div.appendChild(span('log-room', room));
  div.appendChild(span(ok ? 'log-ok' : 'log-err', msg));
  logEl.prepend(div);
  while (logEl.children.length > 100) logEl.removeChild(logEl.lastChild);
}

refreshRooms();
</script>
</body>
</html>`;
