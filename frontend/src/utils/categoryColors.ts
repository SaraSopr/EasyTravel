const categoryColors: Record<string, string> = {
  // English
  museum: 'bg-purple-100 text-purple-700',
  park: 'bg-green-100 text-green-700',
  restaurant: 'bg-orange-100 text-orange-700',
  beach: 'bg-blue-100 text-blue-700',
  nightlife: 'bg-pink-100 text-pink-700',
  shopping: 'bg-yellow-100 text-yellow-700',
  landmark: 'bg-red-100 text-red-700',
  nature: 'bg-emerald-100 text-emerald-700',
}

export const getCategoryColor = (category: string | null | undefined): string =>
  categoryColors[(category ?? '').toLowerCase()] ?? 'bg-gray-100 text-gray-700'
