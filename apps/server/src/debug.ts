import { roomService, DataPacket_Kind } from "./livekit.ts";

export async function handleDebugRooms(): Promise<Response> {
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

  .btn {
    background: var(--charcoal); color: var(--bone); border: 1px solid var(--slate);
    padding: 6px 12px; border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 12px;
    transition: border-color 0.15s, background 0.15s;
  }
  .btn:hover { border-color: var(--hollow); background: var(--slate); }
  .btn:active { background: var(--hollow); color: var(--void); }
  .btn.small { padding: 4px 8px; font-size: 11px; }

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

<div class="section">
  <h2>Dice &amp; Combat</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'dice_result',roll:14,modifier:2,total:16,success:true,roll_type:'skill_check',narrative:'The lock clicks open beneath your nimble fingers.'})">Skill Check Success</button>
    <button class="btn" onclick="send({type:'dice_result',roll:3,modifier:2,total:5,success:false,roll_type:'skill_check',narrative:'The mechanism jams — your pick snaps inside the lock.'})">Skill Check Failure</button>
    <button class="btn" onclick="send({type:'dice_result',roll:20,modifier:4,total:24,success:true,roll_type:'attack',narrative:'A devastating blow! The blade finds the gap in its armor.'})">Critical Hit (Nat 20)</button>
    <button class="btn" onclick="send({type:'combat_started'})">Combat Start</button>
    <button class="btn" onclick="send({type:'combat_ui_update',phase:'player_turn',round:2,combatants:[{id:'c1',name:'Kael',isAlly:true,hpCurrent:24,hpMax:30,statusEffects:[],isActive:true},{id:'c2',name:'Goblin Scout',isAlly:false,hpCurrent:8,hpMax:12,statusEffects:[],isActive:false},{id:'c3',name:'Goblin Shaman',isAlly:false,hpCurrent:15,hpMax:18,statusEffects:['shield'],isActive:false}]})">Combat UI Update</button>
    <button class="btn" onclick="send({type:'combat_ended'})">Combat End (Victory)</button>
  </div>
</div>

<div class="section">
  <h2>Items &amp; Rewards</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'item_acquired',name:'Rusty Dagger',description:'A pitted blade, barely holding its edge.',rarity:'common',stats:{damage:'1d4'}})">Common Item</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Hollow-Touched Compass',description:'The needle drifts toward sources of corruption.',rarity:'uncommon',stats:{corruption_sense:true}})">Uncommon Item</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Veilglass Amulet',description:'A shard of crystallized boundary between worlds.',rarity:'rare',stats:{resist_hollow:'+2',perception:'+1'}})">Rare Item</button>
    <button class="btn" onclick="send({type:'item_acquired',name:'Sundered Edge of Kaelthos',description:'A fragment of a god-forged blade, thrumming with divine wrath.',rarity:'legendary',stats:{damage:'2d8+3',divine_smite:true}})">Legendary Item</button>
    <button class="btn" onclick="send({type:'xp_awarded',new_xp:325,new_level:4,xp_gained:75,level_up:false})">XP +75 (no level-up)</button>
    <button class="btn" onclick="send({type:'xp_awarded',new_xp:1000,new_level:5,xp_gained:250,level_up:true})">Level Up! (xp +250, level 5)</button>
  </div>
</div>

<div class="section">
  <h2>Quest &amp; Location</h2>
  <div class="grid">
    <button class="btn" onclick="send({type:'quest_update',quest_name:'The Greyvale Anomaly',objective:'Investigate the strange lights near the old mill.',status:'active',stage_name:'Discovery'})">Quest Update</button>
    <button class="btn" onclick="send({type:'location_changed',new_location:'greyvale_market',location_name:'Market Square',atmosphere:'Busy stalls and the smell of roasting chestnuts fill the air.',region:'Greyvale'})">Location: Market Square</button>
    <button class="btn" onclick="send({type:'location_changed',new_location:'greyvale_docks',location_name:'The Docks',atmosphere:'Salt wind and creaking ropes. Gulls cry overhead.',region:'Greyvale'})">Location: The Docks</button>
    <button class="btn" onclick="send({type:'location_changed',new_location:'greyvale_tavern',location_name:'The Crowned Hart',atmosphere:'Warm hearth, low murmur of conversation, tankards on oak.',region:'Greyvale'})">Location: The Crowned Hart</button>
  </div>
</div>

<div class="section">
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

<div class="section">
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
  </div>
</div>

<div class="section">
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

function setStatus(text, ok) {
  statusEl.textContent = text;
  statusEl.className = 'status ' + (ok ? 'ok' : 'err');
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
