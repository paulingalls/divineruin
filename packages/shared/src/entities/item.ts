export interface ItemEffect {
  type: string;
  target?: string;
  value?: number | string;
  trigger?: string;
  description?: string;
}

export interface Item {
  id: string;
  name: string;
  tier: 1 | 2;
  type: string;
  subtype?: string;
  rarity: string;
  description?: string;
  tags: string[];
  weight: number;
  effects: ItemEffect[];
  value_base: number;
  value_modifiers?: Record<string, number>;
  lore?: string;
  found_in?: string[];
}
