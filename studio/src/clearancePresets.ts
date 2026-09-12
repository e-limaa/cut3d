/** Initial settings inherited from the prototype; users calibrate to their printer. */
export const clearancePresets = [
  { id: 'PLA', label: 'PLA', clearance: .25 },
  { id: 'PETG', label: 'PETG', clearance: .22 },
  { id: 'ABS', label: 'ABS / ASA', clearance: .20 },
  { id: 'RESIN', label: 'Resina', clearance: .10 },
  { id: 'LOOSE', label: 'Encaixe solto', clearance: .35 },
] as const;
