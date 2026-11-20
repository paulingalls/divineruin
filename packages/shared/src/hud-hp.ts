export interface CharacterHpWire {
  hp_current: number;
  hp_max: number;
  temp_hp: number;
}

export interface HudHp {
  hpCurrent: number;
  hpMax: number;
  tempHp: number;
}

export interface HpChangedWire {
  current: number;
  max?: number;
  temp_hp?: number;
}
