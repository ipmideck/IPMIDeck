// 08-05: single frontend source of truth for BMC vendors.
//
// Mirrors the backend VENDOR_PROFILES (backend/core/ipmi_service.py, plan 08-02)
// EXACTLY — tier + fanCapable per vendor are the same corroborated 08-RESEARCH
// values. Both vendor selects (Setup wizard + Settings) consume this list so the
// six canonical vendors, their tier badges, and the warn-but-allow (D-13) capability
// gate never drift between the two surfaces. Capability/tier is a STATIC constant —
// no backend vendors route is fetched (keeps the Phase-7 route-surface contract intact).
//
//   dell        tier=tested          fanCapable=true   (real R720 validation)
//   supermicro  tier=experimental    fanCapable=true   (X10+ both zones)
//   ibm         tier=experimental    fanCapable=true   (x3550-M4 dual-bank)
//   hpe         tier=monitoring_only fanCapable=false  (iLO exposes no IPMI fan control)
//   lenovo      tier=monitoring_only fanCapable=false  (no reliable in-band restore)
//   generic     tier=monitoring_only fanCapable=false  (unknown BMC — never raw-write)

export type VendorTier = "tested" | "experimental" | "monitoring_only";

export interface VendorMeta {
  value: string;
  labelKey: string;
  tier: VendorTier;
  fanCapable: boolean;
}

export const VENDORS: VendorMeta[] = [
  { value: "dell", labelKey: "vendors.dell", tier: "tested", fanCapable: true },
  { value: "supermicro", labelKey: "vendors.supermicro", tier: "experimental", fanCapable: true },
  { value: "ibm", labelKey: "vendors.ibm", tier: "experimental", fanCapable: true },
  { value: "hpe", labelKey: "vendors.hpe", tier: "monitoring_only", fanCapable: false },
  { value: "lenovo", labelKey: "vendors.lenovo", tier: "monitoring_only", fanCapable: false },
  { value: "generic", labelKey: "vendors.generic", tier: "monitoring_only", fanCapable: false },
];

// i18n key per tier badge (labels translated across all 12 catalogs — see vendorTier.*).
export const TIER_LABEL_KEY: Record<VendorTier, string> = {
  tested: "vendorTier.tested",
  experimental: "vendorTier.experimental",
  monitoring_only: "vendorTier.monitoringOnly",
};

// Canonical vendor value list (re-exported by ServersSection as VENDOR_OPTIONS).
export const VENDOR_VALUES: string[] = VENDORS.map((v) => v.value);

/**
 * True iff the vendor's fan PWM is reachable via a corroborated raw ipmitool
 * sequence (mirrors backend is_fan_capable). Case-insensitive; unknown → false.
 * Drives the warn-but-allow toast (D-13) so hpe/lenovo/generic ALL warn — fixing
 * the old hardcoded unsupported-vendor list that missed 'hp'/'lenovo'.
 */
export function isFanCapable(vendor: string): boolean {
  return VENDORS.find((v) => v.value === (vendor || "").toLowerCase())?.fanCapable ?? false;
}
