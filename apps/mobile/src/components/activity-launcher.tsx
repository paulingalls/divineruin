import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Spacing } from "@/constants/theme";
import { API_BASE, authHeaders } from "@/utils/api";
import type { MaterialRequirement, TemplateItem, TemplateGroup } from "@divineruin/shared";

interface ActivityLauncherProps {
  onStartActivity: (type: string, parameters: Record<string, unknown>) => Promise<void>;
}

function hasSufficientMaterials(materials: MaterialRequirement[] | null): boolean {
  if (!materials || materials.length === 0) return true;
  return materials.every((m) => m.owned >= m.required);
}

function formatTimeRemaining(resolveAt: string): string {
  const remaining = new Date(resolveAt).getTime() - Date.now();
  if (remaining <= 0) return "completing...";
  const hours = Math.floor(remaining / 3_600_000);
  const minutes = Math.floor((remaining % 3_600_000) / 60_000);
  if (hours > 0) return `${hours}h ${minutes}m remaining`;
  return `${minutes}m remaining`;
}

interface ErrandPickerState {
  item: TemplateItem;
  destinations: string[];
}

export function ActivityLauncher({ onStartActivity }: ActivityLauncherProps) {
  const [groups, setGroups] = useState<TemplateGroup[]>([]);
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [startingItemId, setStartingItemId] = useState<string | null>(null);
  const [error, setError] = useState<{ itemId: string; message: string } | null>(null);
  const [errandPicker, setErrandPicker] = useState<ErrandPickerState | null>(null);
  const [pickerSelection, setPickerSelection] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetchTemplates = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/activity-templates`, {
        headers: authHeaders(),
      });
      if (res.ok && mountedRef.current) {
        const data = (await res.json()) as { groups: TemplateGroup[] };
        setGroups(data.groups);
      }
    } catch {
      // Templates will be empty — launcher just won't show
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void fetchTemplates();
    return () => {
      mountedRef.current = false;
    };
  }, [fetchTemplates]);

  const executeStart = useCallback(
    async (type: string, params: Record<string, unknown>, itemId: string) => {
      setStartingItemId(itemId);
      setError(null);
      try {
        await onStartActivity(type, params);
        await fetchTemplates();
      } catch (err) {
        setError({
          itemId,
          message: err instanceof Error ? err.message : "Failed to start activity",
        });
      } finally {
        setStartingItemId(null);
      }
    },
    [onStartActivity, fetchTemplates],
  );

  const handleStart = useCallback(
    (type: string, item: TemplateItem) => {
      if (type === "companion_errand") {
        const destinations = (item.params.valid_destinations ?? []) as string[];
        setErrandPicker({ item, destinations });
        setPickerSelection(null);
        return;
      }

      let params: Record<string, unknown>;
      if (type === "crafting") {
        params = { recipe_id: item.params.recipe_id };
      } else {
        params = { program_id: item.params.program_id };
      }
      void executeStart(type, params, item.id);
    },
    [executeStart],
  );

  const handleErrandConfirm = useCallback(() => {
    if (!errandPicker || !pickerSelection) return;
    const params = {
      errand_type: errandPicker.item.params.errand_type,
      destination: pickerSelection,
    };
    setErrandPicker(null);
    void executeStart("companion_errand", params, errandPicker.item.id);
  }, [errandPicker, pickerSelection, executeStart]);

  if (groups.length === 0) return null;

  return (
    <View style={styles.container}>
      <ThemedText variant="label" themeColor="textSecondary">
        Start an Activity
      </ThemedText>
      {groups.map((group) => {
        // Training and errands are group-locked: only one at a time
        const isGroupLocked = group.type === "training" || group.type === "companion_errand";
        const activeItem = group.items.find((i) => i.active !== null);
        const groupBusy = isGroupLocked && activeItem !== undefined;

        return (
          <View key={group.type} style={styles.groupCard}>
            <Pressable
              style={styles.groupHeader}
              onPress={() => setExpandedType(expandedType === group.type ? null : group.type)}
            >
              <ThemedText variant="h2" style={styles.groupLabel}>
                {group.label}
              </ThemedText>
              {isGroupLocked && activeItem?.active && expandedType !== group.type && (
                <ThemedText style={styles.groupBusyHint}>
                  {formatTimeRemaining(activeItem.active.resolveAtEstimate)}
                </ThemedText>
              )}
              <ThemedText style={styles.chevron}>
                {expandedType === group.type ? "\u25B2" : "\u25BC"}
              </ThemedText>
            </Pressable>

            {expandedType === group.type && (
              <View style={styles.itemList}>
                {isGroupLocked && activeItem?.active && (
                  <View style={styles.groupBusyBanner}>
                    <ThemedText style={styles.groupBusyText}>
                      {group.type === "companion_errand"
                        ? `Kael is on a ${activeItem.name}`
                        : `Currently training: ${activeItem.name}`}
                    </ThemedText>
                    <View style={styles.activeStatus}>
                      <ThemedText style={styles.activeLabel}>IN PROGRESS</ThemedText>
                      <ThemedText style={styles.activeTime}>
                        {formatTimeRemaining(activeItem.active.resolveAtEstimate)}
                      </ThemedText>
                    </View>
                  </View>
                )}
                {group.items.map((item, idx) => {
                  const canStart = hasSufficientMaterials(item.materials);
                  const isActive = item.active !== null;
                  // For crafting: per-item active check. For others: group-level lock.
                  const showStart = !isActive && (!groupBusy || !isGroupLocked);
                  return (
                    <View key={item.id}>
                      {idx > 0 && <View style={styles.divider} />}
                      <View style={styles.itemRow}>
                        <View style={styles.itemInfo}>
                          <ThemedText
                            variant="body"
                            style={[
                              styles.itemName,
                              groupBusy && !isActive && styles.itemNameDimmed,
                            ]}
                          >
                            {item.name}
                          </ThemedText>
                          <ThemedText style={styles.durationText}>{item.duration}</ThemedText>
                        </View>

                        {isActive && !isGroupLocked ? (
                          <View style={styles.activeStatus}>
                            <ThemedText style={styles.activeLabel}>IN PROGRESS</ThemedText>
                            <ThemedText style={styles.activeTime}>
                              {formatTimeRemaining(item.active!.resolveAtEstimate)}
                            </ThemedText>
                          </View>
                        ) : showStart ? (
                          <View style={styles.itemBottomRow}>
                            {item.materials && item.materials.length > 0 && (
                              <View style={styles.materialsColumn}>
                                {item.materials.map((mat) => {
                                  const sufficient = mat.owned >= mat.required;
                                  return (
                                    <ThemedText
                                      key={mat.itemId}
                                      style={[
                                        styles.materialText,
                                        sufficient && styles.materialTextSufficient,
                                      ]}
                                    >
                                      {mat.name} {mat.owned}/{mat.required}
                                    </ThemedText>
                                  );
                                })}
                              </View>
                            )}

                            <Pressable
                              style={[
                                styles.confirmButton,
                                (startingItemId === item.id || !canStart) &&
                                  styles.confirmButtonDisabled,
                              ]}
                              disabled={startingItemId !== null || !canStart}
                              onPress={() => handleStart(group.type, item)}
                            >
                              {startingItemId === item.id ? (
                                <ActivityIndicator size="small" color={BrandColors.ash} />
                              ) : (
                                <ThemedText style={styles.confirmText}>START</ThemedText>
                              )}
                            </Pressable>
                          </View>
                        ) : null}
                      </View>
                      {error?.itemId === item.id && (
                        <View style={styles.errorBanner}>
                          <ThemedText style={styles.errorText}>{error.message}</ThemedText>
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        );
      })}

      <Modal
        visible={errandPicker !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setErrandPicker(null)}
      >
        <Pressable style={styles.modalOverlay} onPress={() => setErrandPicker(null)}>
          <Pressable style={styles.modalContent} onPress={() => {}}>
            <ThemedText variant="h2" style={styles.modalTitle}>
              {errandPicker?.item.name ?? "Choose Destination"}
            </ThemedText>
            <ThemedText style={styles.modalSubtitle}>Where should Kael go?</ThemedText>

            <View style={styles.destList}>
              {errandPicker?.destinations.map((dest) => (
                <Pressable
                  key={dest}
                  style={[styles.destOption, pickerSelection === dest && styles.destOptionSelected]}
                  onPress={() => setPickerSelection(dest)}
                >
                  <ThemedText
                    style={[
                      styles.destOptionText,
                      pickerSelection === dest && styles.destOptionTextSelected,
                    ]}
                  >
                    {dest.replace(/_/g, " ")}
                  </ThemedText>
                </Pressable>
              ))}
            </View>

            <View style={styles.modalActions}>
              <Pressable style={styles.cancelButton} onPress={() => setErrandPicker(null)}>
                <ThemedText style={styles.cancelText}>CANCEL</ThemedText>
              </Pressable>
              <Pressable
                style={[styles.confirmButton, !pickerSelection && styles.confirmButtonDisabled]}
                disabled={!pickerSelection}
                onPress={handleErrandConfirm}
              >
                <ThemedText style={styles.confirmText}>SEND</ThemedText>
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: Spacing.two,
  },
  errorBanner: {
    marginTop: Spacing.one,
    backgroundColor: BrandColors.ember + "22",
    borderWidth: 1,
    borderColor: BrandColors.ember,
    borderRadius: Radius.sm,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  errorText: {
    ...FontStyles.system,
    fontSize: 13,
    color: BrandColors.ember,
  },
  groupCard: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    overflow: "hidden",
  },
  groupHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: Spacing.three,
  },
  groupLabel: {
    flex: 1,
  },
  chevron: {
    fontSize: 12,
    color: BrandColors.ash,
    marginLeft: Spacing.two,
  },
  groupBusyHint: {
    ...FontStyles.systemLight,
    fontSize: 11,
    color: BrandColors.divine,
  },
  itemList: {
    paddingHorizontal: Spacing.three,
    paddingBottom: Spacing.three,
  },
  groupBusyBanner: {
    gap: Spacing.one,
    marginBottom: Spacing.two,
    paddingBottom: Spacing.two,
    borderBottomWidth: 1,
    borderBottomColor: BrandColors.charcoal,
  },
  groupBusyText: {
    ...FontStyles.bodyLightItalic,
    fontSize: 13,
    color: BrandColors.bone,
  },
  divider: {
    height: 1,
    backgroundColor: BrandColors.charcoal,
    marginVertical: Spacing.two,
  },
  itemRow: {
    gap: Spacing.two,
  },
  itemInfo: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  itemBottomRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  itemName: {
    flex: 1,
  },
  itemNameDimmed: {
    opacity: 0.4,
  },
  durationText: {
    ...FontStyles.systemLight,
    fontSize: 12,
    color: BrandColors.ash,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
  materialsColumn: {
    gap: 2,
  },
  materialText: {
    ...FontStyles.system,
    fontSize: 11,
    color: BrandColors.ember,
  },
  materialTextSufficient: {
    color: BrandColors.hollow,
  },
  activeStatus: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  activeLabel: {
    ...FontStyles.system,
    fontSize: 11,
    color: BrandColors.divine,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  activeTime: {
    ...FontStyles.systemLight,
    fontSize: 11,
    color: BrandColors.ash,
  },
  confirmButton: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.one,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  confirmButtonDisabled: {
    borderColor: BrandColors.slate,
    opacity: 0.5,
  },
  confirmText: {
    ...FontStyles.system,
    fontSize: 12,
    color: BrandColors.hollow,
    letterSpacing: 2,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.7)",
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.four,
  },
  modalContent: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    padding: Spacing.four,
    width: "100%",
    maxWidth: 340,
    gap: Spacing.three,
  },
  modalTitle: {
    textAlign: "center",
  },
  modalSubtitle: {
    ...FontStyles.systemLight,
    fontSize: 13,
    color: BrandColors.ash,
    textAlign: "center",
  },
  destList: {
    gap: Spacing.two,
  },
  destOption: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
  },
  destOptionSelected: {
    borderColor: BrandColors.hollowMuted,
    backgroundColor: BrandColors.hollowFaint,
  },
  destOptionText: {
    ...FontStyles.system,
    fontSize: 14,
    color: BrandColors.ash,
    textTransform: "capitalize",
  },
  destOptionTextSelected: {
    color: BrandColors.hollow,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: Spacing.two,
    marginTop: Spacing.one,
  },
  cancelButton: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.one,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
  },
  cancelText: {
    ...FontStyles.system,
    fontSize: 12,
    color: BrandColors.ash,
    letterSpacing: 2,
  },
});
