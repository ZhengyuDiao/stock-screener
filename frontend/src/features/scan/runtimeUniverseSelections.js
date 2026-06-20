import { UNIVERSE_MARKETS, UNIVERSE_SCOPES_BY_MARKET } from './constants';

const SCAN_BLOCKING_ACTIVITY_STAGES = new Set(['prices', 'fundamentals']);
const SCAN_BLOCKING_ACTIVITY_STATUSES = new Set(['queued', 'running']);

function normalizeMarket(value) {
  return value ? String(value).trim().toUpperCase() : null;
}

function hasRuntimeUniverseOptions(universeOptions) {
  return Array.isArray(universeOptions?.markets) && universeOptions.markets.length > 0;
}

function fallbackUniverseSelections() {
  const scopesByMarket = Object.fromEntries(
    Object.entries(UNIVERSE_SCOPES_BY_MARKET).map(([market, options]) => [
      market,
      [
        options[0],
        {
          value: `market:${market}:fresh:true`,
          label: 'Fresh Price Data Only',
          universe_def: { type: 'market', market, fresh_only: true },
        },
        ...options.slice(1),
      ],
    ])
  );
  return {
    markets: UNIVERSE_MARKETS.map((option) => ({
      ...option,
      disabled: false,
      disabledReason: null,
    })),
    scopesByMarket: Object.fromEntries(
      Object.entries(scopesByMarket).map(([market, options]) => [
        market,
        options.map((option) => ({
          ...option,
          disabled: false,
          disabledReason: null,
        })),
      ])
    ),
  };
}

function runtimeScopeOption(option, extras = {}) {
  return {
    value: option.value,
    label: option.label,
    universe_def: option.universe_def,
    aliases: option.aliases ?? [],
    disabled: false,
    disabledReason: null,
    ...extras,
  };
}

export function getMarketScanBlocker(activity, market) {
  const marketCode = normalizeMarket(market);
  if (!marketCode || marketCode === 'TEST') {
    return null;
  }
  const marketActivity = (activity?.markets ?? []).find((item) => (
    normalizeMarket(item?.market) === marketCode
    && SCAN_BLOCKING_ACTIVITY_STAGES.has(item.stage_key)
    && SCAN_BLOCKING_ACTIVITY_STATUSES.has(item.status)
  ));
  if (!marketActivity) {
    return null;
  }
  const stageLabel = marketActivity.stage_label || marketActivity.stage_key || 'Refresh';
  const status = marketActivity.status === 'queued' ? 'queued' : 'running';
  return {
    market: marketCode,
    stageKey: marketActivity.stage_key,
    stageLabel,
    status,
    lifecycle: marketActivity.lifecycle ?? null,
    message: `${marketCode} ${stageLabel.toLowerCase()} is ${status}. Wait for it to finish before starting a scan.`,
  };
}

export function buildRuntimeUniverseSelections(universeOptions, runtimeActivity = null) {
  if (!hasRuntimeUniverseOptions(universeOptions)) {
    return fallbackUniverseSelections();
  }

  const scopesByMarket = {};
  const markets = universeOptions.markets.map((marketOption) => {
    const market = normalizeMarket(marketOption.code);
    const blocker = getMarketScanBlocker(runtimeActivity, market);
    const notEnabled = marketOption.enabled === false;
    const disabled = notEnabled || Boolean(blocker);
    const disabledReason = notEnabled
      ? 'Not enabled'
      : blocker
        ? `${blocker.stageLabel} ${blocker.status}`
        : null;
    const disabledState = { disabled, disabledReason };

    const scopes = [];
    if (marketOption.market) {
      scopes.push(runtimeScopeOption(marketOption.market, { kind: 'market', ...disabledState }));
    }
    if (marketOption.fresh_market) {
      scopes.push(runtimeScopeOption(marketOption.fresh_market, {
        kind: 'fresh_market',
        ...disabledState,
      }));
    }
    for (const mic of marketOption.mics ?? []) {
      scopes.push(runtimeScopeOption(mic, {
        kind: 'mic',
        mic: mic.mic,
        ...disabledState,
      }));
    }
    for (const index of marketOption.indexes ?? []) {
      scopes.push(runtimeScopeOption(index, {
        kind: 'index',
        key: index.key,
        ...disabledState,
      }));
    }
    for (const tier of marketOption.listing_tiers ?? []) {
      scopes.push(runtimeScopeOption(tier, {
        kind: 'listing_tier',
        key: tier.key,
        mic: tier.mic,
        ...disabledState,
      }));
    }
    scopesByMarket[market] = scopes;

    return {
      value: market,
      label: marketOption.label,
      disabled,
      disabledReason,
    };
  });

  markets.push({ value: 'TEST', label: 'Test Mode', disabled: false, disabledReason: null });
  scopesByMarket.TEST = [];
  return { markets, scopesByMarket };
}

export function selectRuntimeUniverseOption(universeSelections, market, scope) {
  const markets = universeSelections?.markets ?? [];
  const scopeOptions = market ? universeSelections?.scopesByMarket?.[market] ?? [] : [];
  return {
    marketOption: markets.find((option) => option.value === market) ?? null,
    scopeOptions,
    scopeOption: scopeOptions.find((option) => option.value === scope) ?? null,
  };
}

export function resolveUniverseScopeValue(market, scope, universeSelections) {
  if (!market || !scope) {
    return scope ?? null;
  }
  const { scopeOptions } = selectRuntimeUniverseOption(universeSelections, market, scope);
  if (scopeOptions.some((option) => option.value === scope)) {
    return scope;
  }
  if (scope === 'market') {
    return scopeOptions.find((option) => (
      option.universe_def?.type === 'market'
      && option.universe_def?.market === market
      && !option.universe_def?.mic
      && !option.universe_def?.listing_tier
    ))?.value ?? scope;
  }
  if (scope.startsWith('index:')) {
    const index = scope.slice('index:'.length);
    return scopeOptions.find((option) => option.universe_def?.index === index)?.value ?? scope;
  }
  if (scope.startsWith('exchange:')) {
    const exchange = scope.slice('exchange:'.length).toUpperCase();
    return scopeOptions.find((option) => (
      option.mic === exchange
      || option.universe_def?.mic === exchange
      || option.aliases?.includes(exchange)
      || option.universe_def?.exchange === exchange
    ))?.value ?? scope;
  }
  return scope;
}
