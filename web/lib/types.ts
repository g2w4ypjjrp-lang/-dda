// API yanıt tipleri (yalnızca arayüzün kullandığı alanlar).

export type Score = { home: number; away: number } | null;
export type TeamRef = { id: number; name: string; short_name: string | null; logo_url: string | null };
export type FixtureStatus =
  | "tbd" | "scheduled" | "live" | "halftime" | "finished" | "postponed" | "suspended" | "cancelled"
  | "abandoned" | "awarded";

export interface Fixture {
  id: number;
  kickoff_at: string;
  kickoff_local: string;
  status: FixtureStatus;
  status_detail: string | null;
  minute: number | null;
  round: string | null;
  competition: { id: number; name: string; logo_url: string | null };
  season: { id: number; year: number; label: string };
  home: TeamRef;
  away: TeamRef;
  score: { current: Score; halftime: Score; fulltime: Score; extratime: Score; penalties: Score };
  source: { provider: string; provider_label: string; source_updated_at: string | null };
  freshness: { fetched_at: string; age_s: number; stale: boolean };
}

export interface DataStatus {
  data_status: "ok" | "no_provider";
  provider: string;
  provider_label: string;
  last_successful_sync_at: string | null;
  last_error_at: string | null;
}

export interface FixtureList extends DataStatus {
  date: string;
  timezone: string;
  items: Fixture[];
}

export type TeamStats = Partial<Record<
  | "shots_total" | "shots_on_target" | "possession_pct" | "corners" | "fouls" | "yellow_cards" | "red_cards"
  | "offsides" | "passes_total" | "passes_accurate" | "goalkeeper_saves" | "xg",
  number | null
>> & { fetched_at: string };

export interface LineupPlayer { id: number; name: string; number: number | null; position: string | null; starter: boolean }
export interface Lineup { formation: string | null; coach: string | null; fetched_at: string; players: LineupPlayer[] }

export interface FixtureDetail extends Fixture {
  venue: { name: string; city: string | null } | null;
  referee: string | null;
  team_stats: Partial<Record<"home" | "away", TeamStats>>;
  lineups: Partial<Record<"home" | "away", Lineup>>;
  absences: { side: "home" | "away" | null; player: string; status: string; category: string; reason: string | null }[];
  completeness: { score: number; issues: { code: string; message: string }[] };
}

export type OneXTwo = { home: number; draw: number; away: number };

export interface Markets {
  "1x2": OneXTwo;
  // FREE pakette yalnızca 1x2 gelir (kısıt sunucuda uygulanır).
  double_chance?: { "1X": number; "12": number; X2: number };
  over_under?: Record<string, { over: number; under: number }>;
  btts?: { yes: number; no: number };
  total_goals?: Record<string, number>;
  correct_score?: { home: number; away: number; p: number }[];
  expected_goals?: { home: number; away: number };
  first_half?: FirstHalf;
}

export type FirstHalf =
  | {
      available: true;
      split: { home: number; away: number };
      "1x2": OneXTwo;
      over_under: Record<string, { over: number; under: number }>;
      btts: { yes: number; no: number };
      correct_score: { home: number; away: number; p: number }[];
      expected_goals: { home: number; away: number };
      ht_ft: Record<string, number>;
      test?: { n: number | null; log_loss: number | null; baseline_log_loss: number | null; ece: number | null };
    }
  | { available: false; reasons: string[] };

export interface Lock { key: string; label: string; required_plan: "PRO" | "ELITE" }

export interface Prediction {
  id: number;
  fixture_id: number;
  created_at: string;
  kickoff_at: string;
  status: "published" | "abstained";
  probabilities: Markets | null;
  reliability: { level: "high" | "medium" | "low"; label: string };
  data_quality: {
    home_history?: number; away_history?: number; xg_coverage?: number; lineups_known?: boolean; stale?: boolean;
  };
  model_agreement: number | null;
  uncertainty: { method?: string; label?: string; samples?: number; interval_1x2?: Record<keyof OneXTwo, [number, number]>; max_width?: number };
  abstain_reasons: { code: string; message: string }[];
  components: Record<string, OneXTwo>;
  model: { version_id: number; status: string; trained_until: string; components: Record<string, number> };
  outcome: { home_goals: number; away_goals: number; result: string; brier: number | null; log_loss: number | null } | null;
  disclaimer: string;
  access?: { plan: string; locked: Lock[] };
}

export interface Performance {
  data_status: "ok" | "no_settled_predictions";
  detail?: string;
  window_days: number;
  settled_published: number;
  settled_abstained: number;
  brier?: number;
  log_loss?: number;
  accuracy?: number;
  uniform_log_loss?: number;
  reliability?: { bin_low: number; bin_high: number; mean_confidence: number; observed_rate: number; count: number }[];
  first_half?: { settled: number; brier: number; log_loss: number } | null;
}

export interface Me {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  mfa_enabled: boolean;
  staff_roles: string[];
  created_at: string;
}

export interface AdminMe {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
  permissions: string[];
  reauth_fresh: boolean;
  session_expires_at: string;
}

/* --- Faz 6: paketler ve ödeme --- */

export type Entitlements = Record<string, boolean | number>;

export interface PlanInfo {
  code: "FREE" | "PRO" | "ELITE";
  name: string;
  tagline: string;
  entitlements: Entitlements;
  prices: Partial<Record<"monthly" | "yearly", { id: number; amount_minor: number; currency: string }>>;
}

export interface Sales { open: boolean; provider: string | null; test_mode: boolean }

export interface PlansResponse { plans: PlanInfo[]; labels: Record<string, string>; sales: Sales; note: string }

export interface Order {
  id: string;
  number: number;
  plan: string;
  period: "monthly" | "yearly";
  amount_minor: number;
  currency: string;
  status: "pending" | "paid" | "failed" | "refunded" | "review";
  provider: string;
  test_mode: boolean;
  created_at: string;
  paid_at: string | null;
  refunded_at: string | null;
}

export interface SubscriptionInfo {
  id: number;
  plan: string;
  status: "active" | "canceled" | "refunded" | "revoked";
  source: "payment" | "license" | "admin";
  started_at: string;
  current_period_end: string;
  in_effect: boolean;
  canceled_at: string | null;
}

export interface BillingMe {
  plan: "FREE" | "PRO" | "ELITE";
  entitlements: Entitlements;
  usage_today: Record<string, number>;
  current: SubscriptionInfo | null;
  subscriptions: SubscriptionInfo[];
  orders: Order[];
  sales: Sales;
}
