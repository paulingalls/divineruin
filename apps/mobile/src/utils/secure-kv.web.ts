// Web: key-value storage backed by localStorage
export function getItem(key: string): Promise<string | null> {
  return Promise.resolve(localStorage.getItem(key));
}

export function setItem(key: string, value: string): Promise<void> {
  localStorage.setItem(key, value);
  return Promise.resolve();
}

export function removeItem(key: string): Promise<void> {
  localStorage.removeItem(key);
  return Promise.resolve();
}
