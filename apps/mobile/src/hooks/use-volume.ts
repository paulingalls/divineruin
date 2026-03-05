import { useCallback, useEffect, useState } from "react";
import { type Bus, getVolume, setVolume, loadVolumes } from "@/audio/volume";

let loadPromise: Promise<void> | null = null;

export function useVolume(bus: Bus) {
  const [value, setValue] = useState(() => getVolume(bus));

  useEffect(() => {
    if (!loadPromise) {
      loadPromise = loadVolumes();
    }
    loadPromise.then(() => setValue(getVolume(bus)));
  }, [bus]);

  const update = useCallback(
    (v: number) => {
      setVolume(bus, v);
      setValue(v);
    },
    [bus],
  );

  return [value, update] as const;
}
