// Fixtures the relay's mock pipeline actually answers (see relay/pipeline/mock.py),
// so both displays demo the same way with no credentials.
export const QUICK_ASKS: Array<{ label: string; text: string }> = [
  { label: 'Torque the M5', text: 'how tight is the m5 on the mounting bracket' },
  { label: 'Clean the housing', text: 'how do i clean the pump housing' },
  { label: 'Walk me through it', text: 'guide me through the mounting bracket assembly' },
  { label: 'Log a deviation', text: 'log deviation: the feeler gauge entered at step 4.2' },
  { label: 'Off-SOP question', text: 'is there a coffee machine in the lab' },
];
