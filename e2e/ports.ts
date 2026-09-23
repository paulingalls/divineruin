function port(name: string): number {
  const raw = process.env[name];
  if (!raw || !/^[1-9][0-9]*$/.test(raw)) throw new Error(`${name} must be a TCP/UDP port`);
  const value = Number(raw);
  if (value > 65535) throw new Error(`${name} exceeds 65535`);
  return value;
}

export const API_PORT = port("E2E_API_PORT");
export const APP_PORT = port("E2E_APP_PORT");
export const WEB_PORT = port("E2E_WEB_PORT");
export const LH_DEBUG_PORT = port("E2E_LH_DEBUG_PORT");
export const API_ORIGIN = `http://localhost:${API_PORT}`;
export const APP_ORIGIN = `http://localhost:${APP_PORT}`;
export const WEB_ORIGIN = `http://localhost:${WEB_PORT}`;
