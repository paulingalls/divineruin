import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, View } from "react-native";
import { useStore } from "zustand";

import {
  activeText,
  errandBusyLabel,
  errandDestinationPrompt,
  getActivityGroupState,
  getLaunchIntent,
  isStartVisible,
  mode,
  trainingBusyLabel,
} from "@/components/activity-launcher-strings";
import { styles } from "@/components/activity-launcher-styles";
import { ThemedText } from "@/components/themed-text";
import { BrandColors } from "@/constants/theme";
import { portraitStore } from "@/stores/portrait-store";
import { API_BASE, authHeaders } from "@/utils/api";
import type { MaterialRequirement, TemplateItem, TemplateGroup } from "@divineruin/shared";

interface ActivityLauncherProps {
  onStartActivity: (type: string, parameters: Record<string, unknown>) => Promise<void>;
}

function hasSufficientMaterials(materials: MaterialRequirement[] | null): boolean {
  if (!materials || materials.length === 0) return true;
  return materials.every((m) => m.owned >= m.required);
}

interface ErrandPickerState {
  item: TemplateItem;
  destinations: string[];
}

interface SpellPickerState {
  item: TemplateItem;
  spellIds: string[];
}

export function ActivityLauncher({ onStartActivity }: ActivityLauncherProps) {
  const [groups, setGroups] = useState<TemplateGroup[]>([]);
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [startingItemId, setStartingItemId] = useState<string | null>(null);
  const [error, setError] = useState<{ itemId: string; message: string } | null>(null);
  const [errandPicker, setErrandPicker] = useState<ErrandPickerState | null>(null);
  const [spellPicker, setSpellPicker] = useState<SpellPickerState | null>(null);
  const [pickerSelection, setPickerSelection] = useState<string | null>(null);
  const companionName = useStore(portraitStore, (s) => s.companionName);
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

      const intent = getLaunchIntent(type as "crafting" | "training", item);
      if (intent.kind === "choose-spell") {
        setSpellPicker({ item, spellIds: intent.spellIds });
        setPickerSelection(null);
        return;
      }
      if (intent.kind === "disabled") return;
      void executeStart(type, intent.params, item.id);
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

  const handleSpellConfirm = useCallback(() => {
    if (!spellPicker || !pickerSelection) return;
    const intent = getLaunchIntent("training", spellPicker.item, pickerSelection);
    if (intent.kind !== "ready") return;
    setSpellPicker(null);
    setPickerSelection(null);
    void executeStart("training", intent.params, spellPicker.item.id);
  }, [spellPicker, pickerSelection, executeStart]);

  if (groups.length === 0) return null;

  return (
    <View style={styles.container}>
      <ThemedText variant="label" themeColor="textSecondary">
        Start an Activity
      </ThemedText>
      {groups.map((group) => {
        const groupState = getActivityGroupState(group);
        const { isGroupLocked, activeItem, groupBusy } = groupState;

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
                  {activeText(activeItem.active)}
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
                        ? errandBusyLabel(companionName, activeItem.name)
                        : trainingBusyLabel(activeItem.name)}
                    </ThemedText>
                    <View style={styles.activeStatus}>
                      <ThemedText style={styles.activeLabel}>{mode(activeItem.active)}</ThemedText>
                      <ThemedText style={styles.activeTime}>
                        {activeText(activeItem.active)}
                      </ThemedText>
                    </View>
                  </View>
                )}
                {group.items.map((item, idx) => {
                  const canStart = hasSufficientMaterials(item.materials);
                  const launchIntent =
                    group.type === "crafting" || group.type === "training"
                      ? getLaunchIntent(group.type, item)
                      : null;
                  const disabledReason =
                    launchIntent?.kind === "disabled" ? launchIntent.reason : null;
                  const isActive = item.active !== null;
                  const showStart = isStartVisible(item, groupState);
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
                        {disabledReason && (
                          <ThemedText style={styles.disabledReason}>{disabledReason}</ThemedText>
                        )}

                        {isActive && !isGroupLocked ? (
                          <View style={styles.activeStatus}>
                            <ThemedText style={styles.activeLabel}>{mode(item.active!)}</ThemedText>
                            <ThemedText style={styles.activeTime}>
                              {activeText(item.active!)}
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
                                (startingItemId === item.id ||
                                  !canStart ||
                                  disabledReason !== null) &&
                                  styles.confirmButtonDisabled,
                              ]}
                              disabled={
                                startingItemId !== null || !canStart || disabledReason !== null
                              }
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
            <ThemedText style={styles.modalSubtitle}>
              {errandDestinationPrompt(companionName)}
            </ThemedText>

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

      <Modal
        visible={spellPicker !== null}
        transparent
        animationType="fade"
        onRequestClose={() => {
          setSpellPicker(null);
          setPickerSelection(null);
        }}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => {
            setSpellPicker(null);
            setPickerSelection(null);
          }}
        >
          <Pressable style={styles.modalContent} onPress={() => {}}>
            <ThemedText variant="h2" style={styles.modalTitle}>
              {spellPicker?.item.name ?? "Choose Spell"}
            </ThemedText>
            <ThemedText style={styles.modalSubtitle}>Choose a spell to study.</ThemedText>
            <View style={styles.destList}>
              {spellPicker?.spellIds.map((spellId) => (
                <Pressable
                  key={spellId}
                  style={[
                    styles.destOption,
                    pickerSelection === spellId && styles.destOptionSelected,
                  ]}
                  onPress={() => setPickerSelection(spellId)}
                >
                  <ThemedText
                    style={[
                      styles.destOptionText,
                      pickerSelection === spellId && styles.destOptionTextSelected,
                    ]}
                  >
                    {spellId.replace(/_/g, " ")}
                  </ThemedText>
                </Pressable>
              ))}
            </View>
            <View style={styles.modalActions}>
              <Pressable
                style={styles.cancelButton}
                onPress={() => {
                  setSpellPicker(null);
                  setPickerSelection(null);
                }}
              >
                <ThemedText style={styles.cancelText}>CANCEL</ThemedText>
              </Pressable>
              <Pressable
                style={[styles.confirmButton, !pickerSelection && styles.confirmButtonDisabled]}
                disabled={!pickerSelection}
                onPress={handleSpellConfirm}
              >
                <ThemedText style={styles.confirmText}>STUDY</ThemedText>
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
