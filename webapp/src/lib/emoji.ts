// Emoji characters for the hangout map: who's who, how they travel, what kind of place.
import type { PlaceKind, TravelMode } from './types'

/** Full-body, gender-neutral figures (we never guess someone's gender from their name). */
const FIGURES = ['🧙', '🧚', '🧝', '🥷', '🧛', '🧜', '🧞', '🦹', '🧑‍🚀', '🧑‍🎤', '🧑‍🍳', '🧟']

/** Same person, same figure, every time (keyed by id, not by position in a group). */
export const figureOf = (personId: number, isMe: boolean) => (isMe ? '🦸' : FIGURES[personId % FIGURES.length])

export const MODE_EMOJI: Record<TravelMode, string> = { walk: '🚶', bike: '🚲', drive: '🚗' }

export const KIND_EMOJI: Record<PlaceKind, string> = {
  restaurant: '🍜',
  cafe: '☕',
  bar: '🍹',
  retail: '🛍️',
  activity: '🎳',
}
