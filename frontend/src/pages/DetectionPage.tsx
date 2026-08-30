/**
 * Detection pipeline.
 *
 * The two-tier design was previously invisible from the console: incidents
 * appeared with no way to see which detector produced them, on what thresholds,
 * or why the ML tier is switched off. This page reads GET /ai/detection/status
 * and reports exactly what the backend says.
 *
 * Two rules it holds to, both of which the rest of this console already follows:
 *
 *  1. Nothing is inferred. A metric the evaluation record does not carry renders
 *     as "not recorded", never as zero — the difference between an unmeasured
 *     model and a model that scored nothing is the whole point of this screen.
 *  2. The unflattering number leads. Leave-one-flight-out is presented as the
 *     result; the row-level split is shown beside it as a contrast, labelled as
 *     leaky, because the gap between the two is the actual finding.
 */

import { useQuery } from "@tanstack/react-query";
import { api, type DetectionTier } from "@/services/api";
import {
  ErrorState,
  LoadingState,
  PermissionDeniedState,
  UnavailableState,
} from "@/components/ui/DataState";
import { Icon } from "@/components/ui/Icon";
import {
  Chip,
  Mono,
  PageHeader,
  Panel,
  PanelBody,
  PanelHeader,
  Table,
  Td,
  Th,
} from "@/components/ui/primitives";
import { humanizeEnum, num } from "@/lib/format";
import { hasPermission, Permissions } from "@/lib/rbac";
import { useAuth } from "@/hooks/useAuth";

const ABSENT = "—";

/** Renders a 0–1 metric as a percentage, or "not recorded" when absent. */
function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number | null | undefined;
  hint?: string;
  tone?: "critical";
}) {
  const present = value !== null && value !== undefined && Number.isFinite(value);

  return (
    <div>
      <dt className="text-[11px] text-content-dim">{label}</dt>
      <dd className="mt-0.5">
        {present ? (
          <Mono className={tone === "critical" ? "text-[15px] text-critical" : "text-[15px] text-content"}>
            {num(value, 3)}
          </Mono>
        ) : (
          <span className="text-[12px] text-content-dim">Not recorded</span>
        )}
      </dd>
      {hint ? <p className="mt-0.5 text-[11px] text-content-dim">{hint}</p> : null}
    </div>
  );
}

function TierBadge({ tier }: { tier: DetectionTier }) {
  if (!tier.enabled) {
    return <Chip tone="neutral">Disabled</Chip>;
  }
  return tier.raises_incidents ? (
    <Chip tone="accent">Live — raises incidents</Chip>
  ) : (
    <Chip tone="warning">Enabled — advisory only</Chip>
  );
}

/* ----------------------------------------------------------------- Tier 1 */

function KinematicGuardPanel({ tier }: { tier: DetectionTier }) {
  return (
    <Panel>
      <PanelHeader
        title={`Tier ${tier.tier} — ${tier.name}`}
        description={tier.method}
        actions={<TierBadge tier={tier} />}
      />

      <PanelBody className="pb-0">
        <div className="flex flex-wrap gap-1.5">
          {tier.deterministic ? <Chip tone="accent">Deterministic</Chip> : null}
          {!tier.requires_training_data ? <Chip>No training data required</Chip> : null}
          <Chip>
            <Mono>{tier.detector}</Mono>
          </Chip>
        </div>

        <p className="mt-3 max-w-[80ch] text-[12px] leading-relaxed text-content-muted">
          Thresholds describe the airframe&rsquo;s envelope with margin, so a manoeuvre the
          aircraft is physically capable of cannot trip them. Every alert carries the observed
          value and the limit it crossed, which means an analyst can re-check the arithmetic
          rather than trusting a score.
        </p>
      </PanelBody>

      {tier.checks && tier.checks.length > 0 ? (
        <div className="mt-3">
          <Table>
            <thead>
              <tr>
                <Th>Check</Th>
                <Th className="text-right">Limit</Th>
                <Th>What it measures</Th>
              </tr>
            </thead>
            <tbody>
              {tier.checks.map((check) => (
                <tr key={check.check}>
                  <Td>
                    <Mono className="text-content">{check.check}</Mono>
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    <Mono className="text-content-muted">
                      {check.lower_is_worse ? "below " : "above "}
                      {num(check.threshold, check.unit === "satellites" ? 0 : 1)} {check.unit}
                    </Mono>
                  </Td>
                  <Td>
                    <span className="text-[12px] text-content-muted">{check.description}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : (
        <UnavailableState
          compact
          title="No checks reported"
          detail="The backend did not report any configured checks for this tier."
        />
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- Tier 2 */

function ModelTierPanel({ tier }: { tier: DetectionTier }) {
  const v = tier.validation;
  const contrast = tier.contrast;

  return (
    <Panel>
      <PanelHeader
        title={`Tier ${tier.tier} — ${tier.name}`}
        description={tier.method}
        actions={<TierBadge tier={tier} />}
      />

      <PanelBody className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          <div>
            <dt className="text-[11px] text-content-dim">Model version</dt>
            <dd className="mt-0.5">
              {tier.model_version ? (
                <Mono className="text-[13px] text-content">{tier.model_version}</Mono>
              ) : (
                <span className="text-[12px] text-content-dim">Not recorded</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-content-dim">Artifact</dt>
            <dd className="mt-0.5">
              <Chip tone={tier.artifact_status === "present" ? "accent" : "critical"}>
                {humanizeEnum(tier.artifact_status ?? "UNKNOWN")}
              </Chip>
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-content-dim">Features</dt>
            <dd className="mt-0.5">
              <Mono className="text-[13px] text-content">
                {tier.feature_list?.length ?? ABSENT}
              </Mono>
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-content-dim">Validation folds</dt>
            <dd className="mt-0.5">
              <Mono className="text-[13px] text-content">{v?.n_folds ?? ABSENT}</Mono>
            </dd>
          </div>
        </dl>

        {/* The honest result. */}
        <section className="rounded-control border border-line bg-surface-overlay p-3">
          <h3 className="text-[12px] font-semibold text-content">
            Measured performance — {v?.protocol ?? "protocol not recorded"}
          </h3>
          <p className="mt-1 max-w-[80ch] text-[11px] leading-relaxed text-content-muted">
            Trained on every flight but one and tested on the held-out flight, repeated across all
            flights. In this dataset each flight is entirely one attack type, so a random row split
            would put rows from the same flight in both train and test and the model could memorise
            flight identity instead of attack behaviour.
          </p>

          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            <Metric label="Precision" value={v?.precision} />
            <Metric label="Recall" value={v?.recall} />
            <Metric label="F1" value={v?.f1_score} tone="critical" />
            <Metric
              label="False positive rate"
              value={v?.false_positive_rate}
              tone="critical"
              hint="Share of normal rows flagged"
            />
          </dl>
        </section>

        {/* The contrast, explicitly labelled as leaky. */}
        {contrast?.f1_score !== null && contrast?.f1_score !== undefined ? (
          <section className="rounded-control border border-line-subtle p-3">
            <h3 className="text-[12px] font-semibold text-content-muted">
              For contrast — {contrast.protocol}
            </h3>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-2">
              <Metric label="F1" value={contrast.f1_score} />
              {v?.f1_score ? (
                <div>
                  <dt className="text-[11px] text-content-dim">Gap</dt>
                  <dd className="mt-0.5">
                    <Mono className="text-[15px] text-warning">
                      {(contrast.f1_score / v.f1_score).toFixed(1)}×
                    </Mono>
                  </dd>
                </div>
              ) : null}
            </div>
            {contrast.caveat ? (
              <p className="mt-2 flex items-start gap-2 text-[11px] leading-relaxed text-content-dim">
                <Icon name="info" size={13} className="mt-0.5 shrink-0" />
                <span>{contrast.caveat}</span>
              </p>
            ) : null}
          </section>
        ) : null}

        {tier.disabled_reason ? (
          <p className="flex items-start gap-2 rounded-control border border-warning/35 bg-warning-wash px-3 py-2 text-[12px] leading-relaxed text-warning">
            <Icon name="alert" size={13} className="mt-0.5 shrink-0" />
            <span>{tier.disabled_reason}</span>
          </p>
        ) : null}

        {/* What was tried, and why each attempt was rejected. Without this the
            page says a tier is off but not that the alternatives were measured. */}
        {tier.investigations?.interventions?.length ? (
          <section>
            <h3 className="text-[12px] font-semibold text-content">What has been tried</h3>
            <p className="mt-0.5 text-[11px] leading-relaxed text-content-dim">
              Each result is leave-one-flight-out. The reference point is a classifier that
              always says &ldquo;attack&rdquo; and needs no model at all
              {tier.investigations.trivial_baselines?.always_say_attack?.f1_score != null
                ? <> &mdash; F1{" "}
                    <Mono className="text-content-muted">
                      {num(tier.investigations.trivial_baselines.always_say_attack.f1_score, 3)}
                    </Mono>
                  </>
                : null}
              . An intervention that does not clear it is not adding information.
            </p>

            <ul className="mt-2.5 flex flex-col gap-2">
              {tier.investigations.interventions.map((step) => (
                <li
                  key={step.id}
                  className="rounded-control border border-line bg-surface-overlay p-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <span className="text-[12px] font-medium text-content">{step.name}</span>
                    <span className="flex shrink-0 items-baseline gap-2.5">
                      {step.lofo?.f1_score != null ? (
                        <Mono className="text-[12px] text-content-muted">
                          F1 {num(step.lofo.f1_score, 3)}
                        </Mono>
                      ) : null}
                      {step.lofo?.false_positive_rate != null ? (
                        <Mono className="text-[12px] text-content-dim">
                          FPR {num(step.lofo.false_positive_rate, 3)}
                        </Mono>
                      ) : null}
                      <Chip tone={step.verdict === "invalid" ? "critical" : "neutral"}>
                        {humanizeEnum(step.verdict)}
                      </Chip>
                    </span>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-content-muted">
                    {step.reason}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {tier.investigations?.root_cause?.finding ? (
          <section className="rounded-control border border-line bg-surface-overlay p-3">
            <h3 className="text-[12px] font-semibold text-content">
              {tier.investigations.root_cause.finding}
            </h3>
            {tier.investigations.root_cause.evidence?.length ? (
              <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4">
                {tier.investigations.root_cause.evidence.map((line) => (
                  <li key={line} className="text-[11px] leading-relaxed text-content-muted">
                    {line}
                  </li>
                ))}
              </ul>
            ) : null}
            {tier.investigations.root_cause.implication ? (
              <p className="mt-2 text-[11px] leading-relaxed text-content-dim">
                {tier.investigations.root_cause.implication}
              </p>
            ) : null}
          </section>
        ) : null}

        {tier.feature_list && tier.feature_list.length > 0 ? (
          <div>
            <h3 className="text-[12px] font-semibold text-content">Input features</h3>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {tier.feature_list.map((feature) => (
                <li key={feature}>
                  <Chip>
                    <Mono>{feature}</Mono>
                  </Chip>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </PanelBody>
    </Panel>
  );
}

/* ------------------------------------------------------------------- page */

export default function DetectionPage() {
  const { user, role } = useAuth();
  const canRead = hasPermission(user?.role ?? role, Permissions.AI_EXPLAIN);

  const statusQuery = useQuery({
    queryKey: ["detection-status"],
    queryFn: () => api.getDetectionStatus(),
    enabled: canRead,
    // Configuration, not telemetry. It changes on redeploy, not on a timer.
    staleTime: 60_000,
  });

  if (!canRead) {
    return (
      <>
        <PageHeader title="Detection pipeline" />
        <Panel>
          <PermissionDeniedState detail="Reading detector configuration requires the ai.explain permission." />
        </Panel>
      </>
    );
  }

  const tiers = statusQuery.data?.tiers ?? [];
  const authoritative = tiers.find((t) => t.raises_incidents);

  return (
    <>
      <PageHeader
        title="Detection pipeline"
        description="What is detecting, on what settings, and how well it was measured to work."
        actions={
          authoritative ? (
            <Chip tone="accent">
              Authoritative: {authoritative.name}
            </Chip>
          ) : (
            <Chip tone="critical">No detector is raising incidents</Chip>
          )
        }
      />

      {statusQuery.isLoading ? (
        <Panel>
          <LoadingState rows={8} />
        </Panel>
      ) : statusQuery.isError ? (
        <Panel>
          <ErrorState error={statusQuery.error} onRetry={() => statusQuery.refetch()} />
        </Panel>
      ) : tiers.length === 0 ? (
        <Panel>
          <UnavailableState
            title="No tiers reported"
            detail="The backend returned no detection tiers, so nothing can be shown."
          />
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Switched on the detector name rather than the presence of a field,
              so a tier that reports no checks still renders as the guard it is
              instead of silently falling through to the model layout. */}
          {tiers.map((tier) =>
            tier.detector === "kinematic_guard" ? (
              <KinematicGuardPanel key={tier.tier} tier={tier} />
            ) : (
              <ModelTierPanel key={tier.tier} tier={tier} />
            ),
          )}

          <Panel>
            <PanelBody>
              <h2 className="text-[13px] font-semibold text-content">Why physics is authoritative</h2>
              <p className="mt-1 max-w-[80ch] text-[12px] leading-relaxed text-content-muted">
                A detector with a high false-positive rate does not degrade gracefully. It trains
                operators to dismiss the dashboard, which leaves them worse off than having no
                dashboard at all. The kinematic guard catches gross manipulation rather than subtle
                drift — it is the floor, not the ceiling — but it is deterministic, carries no
                training-set assumptions into a new deployment, and every alert it raises can be
                checked by hand.
              </p>
            </PanelBody>
          </Panel>
        </div>
      )}
    </>
  );
}
