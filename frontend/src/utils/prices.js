export const PRICE_PRIMARY_TO_FIELD = {
  market: 'price_market',
  avg: 'price_market',
  trend: 'price_trend',
  avg1: 'price_avg1',
  avg7: 'price_avg7',
  avg30: 'price_avg30',
  low: 'price_low',
}

export const HOLO_VARIANTS = new Set(['Holo', 'Holo Rare', 'Holo V', 'Holo VMAX', 'Holo VSTAR', 'Holo ex', 'Reverse Holo'])

export const HOLO_FIELD_MAP = {
  price_market: 'price_market_holo',
  price_trend: 'price_trend_holo',
  price_avg1: 'price_avg1_holo',
  price_avg7: 'price_avg7_holo',
  price_avg30: 'price_avg30_holo',
  price_low: 'price_low_holo',
}

export function priceFieldFromPrimary(pricePrimary) {
  return PRICE_PRIMARY_TO_FIELD[pricePrimary] || 'price_trend'
}

export function getEffectiveCardPrice(card, variant, priceField = 'price_trend') {
  if (!card) return 0
  if (HOLO_VARIANTS.has(variant)) {
    const holoField = HOLO_FIELD_MAP[priceField]
    const holoValue = holoField ? card[holoField] : null
    if (holoValue != null) return Number(holoValue) || 0
  }
  return Number(card[priceField] ?? card.price_market ?? 0) || 0
}
