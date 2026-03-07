import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Radius, Spacing } from "@/constants/theme";
import { API_BASE, authHeaders } from "@/utils/api";

interface TemplateItem {
  id: string;
  name: string;
  duration: string;
  params: Record<string, unknown>;
}

interface TemplateGroup {
  type: string;
  label: string;
  items: TemplateItem[];
}

interface ActivityLauncherProps {
  onStartActivity: (type: string, parameters: Record<string, unknown>) => Promise<void>;
}

export function ActivityLauncher({ onStartActivity }: ActivityLauncherProps) {
  const [groups, setGroups] = useState<TemplateGroup[]>([]);
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [selectedErrandDest, setSelectedErrandDest] = useState<Record<string, string>>({});
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/activity-templates`, {
          headers: authHeaders(),
        });
        if (res.ok) {
          const data = (await res.json()) as { groups: TemplateGroup[] };
          setGroups(data.groups);
        }
      } catch {
        // Templates will be empty — launcher just won't show
      }
    })();
  }, []);

  const handleStart = useCallback(
    async (type: string, item: TemplateItem) => {
      setStarting(true);
      try {
        let params: Record<string, unknown>;
        if (type === "crafting") {
          params = { recipe_id: item.params.recipe_id };
        } else if (type === "training") {
          params = { program_id: item.params.program_id };
        } else {
          // companion_errand — need destination
          const dest = selectedErrandDest[item.id];
          if (!dest) return;
          params = { errand_type: item.params.errand_type, destination: dest };
        }
        await onStartActivity(type, params);
        setExpandedType(null);
      } catch {
        // Error handling in parent
      } finally {
        setStarting(false);
      }
    },
    [onStartActivity, selectedErrandDest],
  );

  if (groups.length === 0) return null;

  return (
    <View style={styles.container}>
      <ThemedText variant="label" themeColor="textSecondary">
        Start an Activity
      </ThemedText>
      {groups.map((group) => (
        <View key={group.type} style={styles.groupCard}>
          <Pressable
            style={styles.groupHeader}
            onPress={() => setExpandedType(expandedType === group.type ? null : group.type)}
          >
            <ThemedText variant="h2" style={styles.groupLabel}>
              {group.label}
            </ThemedText>
            <ThemedText style={styles.chevron}>
              {expandedType === group.type ? "\u25B2" : "\u25BC"}
            </ThemedText>
          </Pressable>

          {expandedType === group.type && (
            <View style={styles.itemList}>
              {group.items.map((item, idx) => (
                <View key={item.id}>
                  {idx > 0 && <View style={styles.divider} />}
                  <View style={styles.itemRow}>
                    <View style={styles.itemInfo}>
                      <ThemedText variant="body" style={styles.itemName}>
                        {item.name}
                      </ThemedText>
                      <ThemedText style={styles.durationText}>{item.duration}</ThemedText>
                    </View>

                    {group.type === "companion_errand" && (
                      <ScrollView
                        horizontal
                        showsHorizontalScrollIndicator={false}
                        style={styles.destScroll}
                        contentContainerStyle={styles.destRow}
                      >
                        {((item.params.valid_destinations ?? []) as string[]).map((dest) => (
                          <Pressable
                            key={dest}
                            style={[
                              styles.destChip,
                              selectedErrandDest[item.id] === dest && styles.destChipSelected,
                            ]}
                            onPress={() =>
                              setSelectedErrandDest((prev) => ({
                                ...prev,
                                [item.id]: dest,
                              }))
                            }
                          >
                            <ThemedText
                              style={[
                                styles.destText,
                                selectedErrandDest[item.id] === dest && styles.destTextSelected,
                              ]}
                            >
                              {dest.replace(/_/g, " ")}
                            </ThemedText>
                          </Pressable>
                        ))}
                      </ScrollView>
                    )}

                    <Pressable
                      style={[styles.confirmButton, starting && styles.confirmButtonDisabled]}
                      disabled={
                        starting ||
                        (group.type === "companion_errand" && !selectedErrandDest[item.id])
                      }
                      onPress={() => void handleStart(group.type, item)}
                    >
                      {starting ? (
                        <ActivityIndicator size="small" color={BrandColors.ash} />
                      ) : (
                        <ThemedText style={styles.confirmText}>START</ThemedText>
                      )}
                    </Pressable>
                  </View>
                </View>
              ))}
            </View>
          )}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: Spacing.two,
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
  },
  itemList: {
    paddingHorizontal: Spacing.three,
    paddingBottom: Spacing.three,
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
  itemName: {
    flex: 1,
  },
  durationText: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 12,
    color: BrandColors.ash,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
  destScroll: {
    maxHeight: 32,
  },
  destRow: {
    gap: Spacing.one,
  },
  destChip: {
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.one,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
  },
  destChipSelected: {
    borderColor: BrandColors.hollowMuted,
    backgroundColor: BrandColors.hollowFaint,
  },
  destText: {
    fontFamily: FontFamilies.system,
    fontSize: 11,
    color: BrandColors.ash,
    textTransform: "capitalize",
  },
  destTextSelected: {
    color: BrandColors.hollow,
  },
  confirmButton: {
    alignSelf: "flex-end",
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
    fontFamily: FontFamilies.system,
    fontSize: 12,
    color: BrandColors.hollow,
    letterSpacing: 2,
  },
});
