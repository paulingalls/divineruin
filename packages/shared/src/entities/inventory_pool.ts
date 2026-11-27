export interface InventoryPoolStock {
  item_id: string;
  quantity: number;
  price: number;
}

export interface InventoryPool {
  id: string;
  name: string;
  location: string;
  type: string;
  restock_interval_hours: number;
  items: InventoryPoolStock[];
  buys: "all" | string[];
  buys_rarities: string[];
}
