import { describe, expect, it } from 'vitest';

import {
  buildRuntimeUniverseSelections,
  resolveUniverseScopeValue,
  selectRuntimeUniverseOption,
} from './runtimeUniverseSelections';

const runtimeUniverseOptions = {
  version: 'test.v1',
  supported_markets: ['US', 'HK'],
  enabled_markets: ['US'],
  markets: [
    {
      code: 'US',
      label: 'United States',
      enabled: true,
      market: {
        value: 'market:US',
        label: 'All United States',
        universe_def: { type: 'market', market: 'US' },
      },
      fresh_market: {
        value: 'market:US:fresh:true',
        label: 'Fresh Price Data Only',
        universe_def: { type: 'market', market: 'US', fresh_only: true },
      },
      mics: [
        {
          value: 'market:US:mic:XNYS',
          label: 'XNYS',
          mic: 'XNYS',
          aliases: ['NYSE'],
          universe_def: { type: 'market', market: 'US', mic: 'XNYS' },
        },
      ],
      indexes: [
        {
          value: 'index:SP500',
          label: 'S&P 500',
          key: 'SP500',
          aliases: [],
          universe_def: { type: 'index', index: 'SP500' },
        },
      ],
      listing_tiers: [],
    },
    {
      code: 'HK',
      label: 'Hong Kong',
      enabled: false,
      market: {
        value: 'market:HK',
        label: 'All Hong Kong',
        universe_def: { type: 'market', market: 'HK' },
      },
      fresh_market: {
        value: 'market:HK:fresh:true',
        label: 'Fresh Price Data Only',
        universe_def: { type: 'market', market: 'HK', fresh_only: true },
      },
      mics: [
        {
          value: 'market:HK:mic:XHKG',
          label: 'XHKG',
          mic: 'XHKG',
          aliases: ['HKEX', 'SEHK'],
          universe_def: { type: 'market', market: 'HK', mic: 'XHKG' },
        },
      ],
      indexes: [
        {
          value: 'index:HSI',
          label: 'Hang Seng Index',
          key: 'HSI',
          aliases: [],
          universe_def: { type: 'index', index: 'HSI' },
        },
      ],
      listing_tiers: [
        {
          value: 'market:HK:mic:XHKG:tier:main_board',
          label: 'Main Board',
          key: 'main_board',
          mic: 'XHKG',
          aliases: ['MAIN'],
          universe_def: {
            type: 'market',
            market: 'HK',
            mic: 'XHKG',
            listing_tier: 'main_board',
          },
        },
      ],
    },
  ],
};

describe('buildRuntimeUniverseSelections', () => {
  it('builds market and universe options from runtime capabilities', () => {
    const selections = buildRuntimeUniverseSelections(runtimeUniverseOptions);

    expect(selections.markets).toEqual([
      expect.objectContaining({ value: 'US', label: 'United States', disabled: false }),
      expect.objectContaining({ value: 'HK', label: 'Hong Kong', disabled: true }),
      expect.objectContaining({ value: 'TEST', label: 'Test Mode', disabled: false }),
    ]);
    expect(selections.scopesByMarket.HK).toEqual([
      expect.objectContaining({
        value: 'market:HK',
        label: 'All Hong Kong',
        universe_def: { type: 'market', market: 'HK' },
      }),
      expect.objectContaining({
        value: 'market:HK:fresh:true',
        label: 'Fresh Price Data Only',
        universe_def: { type: 'market', market: 'HK', fresh_only: true },
      }),
      expect.objectContaining({
        value: 'market:HK:mic:XHKG',
        label: 'XHKG',
        universe_def: { type: 'market', market: 'HK', mic: 'XHKG' },
      }),
      expect.objectContaining({
        value: 'index:HSI',
        label: 'Hang Seng Index',
        universe_def: { type: 'index', index: 'HSI' },
      }),
      expect.objectContaining({
        value: 'market:HK:mic:XHKG:tier:main_board',
        label: 'Main Board',
        universe_def: {
          type: 'market',
          market: 'HK',
          mic: 'XHKG',
          listing_tier: 'main_board',
        },
      }),
    ]);
  });

  it('disables markets with active scan-blocking runtime activity', () => {
    const selections = buildRuntimeUniverseSelections(
      runtimeUniverseOptions,
      {
        markets: [
          {
            market: 'US',
            stage_key: 'prices',
            stage_label: 'Price Refresh',
            status: 'running',
          },
        ],
      }
    );

    expect(selections.markets.find((market) => market.value === 'US')).toEqual(
      expect.objectContaining({ disabled: true, disabledReason: 'Price Refresh running' })
    );
  });

  it('normalizes legacy default scopes to runtime option values', () => {
    const selections = buildRuntimeUniverseSelections(runtimeUniverseOptions);

    expect(resolveUniverseScopeValue('HK', 'market', selections)).toBe('market:HK');
    expect(resolveUniverseScopeValue('US', 'exchange:NYSE', selections)).toBe('market:US:mic:XNYS');
    expect(resolveUniverseScopeValue('US', 'index:SP500', selections)).toBe('index:SP500');
  });
});

describe('selectRuntimeUniverseOption', () => {
  it('returns the selected market, market scopes, and selected scope as one view model', () => {
    const selections = buildRuntimeUniverseSelections(runtimeUniverseOptions);

    expect(selectRuntimeUniverseOption(
      selections,
      'HK',
      'market:HK:mic:XHKG:tier:main_board'
    )).toEqual({
      marketOption: expect.objectContaining({ value: 'HK', label: 'Hong Kong' }),
      scopeOptions: expect.arrayContaining([
        expect.objectContaining({ value: 'market:HK:mic:XHKG:tier:main_board' }),
      ]),
      scopeOption: expect.objectContaining({
        value: 'market:HK:mic:XHKG:tier:main_board',
        universe_def: {
          type: 'market',
          market: 'HK',
          mic: 'XHKG',
          listing_tier: 'main_board',
        },
      }),
    });
  });
});
