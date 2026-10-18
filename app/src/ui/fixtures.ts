// Synthetic UI fixtures only. Part 2 owns the app's actual mock/audio/API modules.
import type { AskResponse, Assignment } from '../types';
const answered: AskResponse = {
    trace_id: 'fixture-answer', transcript: 'What torque for the M5 screws?', intent: 'question',
    outcome: 'answered', glance: 'Torque M5 bracket screws to 4 N-m.',
    body: 'Torque all four M5 bracket screws to 4 N-m in a star pattern. Use a calibrated wrench. Confirm the bracket is seated on both dowel pins before tightening. Mark each screw after checking torque. This is a synthetic training procedure.',
    source: 'SOP-114 Sec 4.2 rev C', verified: true,
    citations: [{ chunk_id: 'synthetic-114-42', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: 'Torque all four M5 bracket screws to 4 N-m in a star pattern.' }],
    walkthrough: null, latency_ms: { stt: 0, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 0 },
};
export const FIXTURE_NAMES = ['answer', 'not_found', 'error', 'walkthrough', 'logged'] as const;
export const UI_FIXTURES: Readonly<Record<typeof FIXTURE_NAMES[number], AskResponse>> = {
    answer: answered,
    not_found: { ...answered, trace_id: 'fixture-not-found', outcome: 'not_found', verified: false,
        glance: 'Not in approved SOPs', body: 'No matching procedure. Try rephrasing or ask your supervisor.', citations: [] },
    error: { ...answered, trace_id: 'fixture-error', outcome: 'error', verified: false, glance: '', body: '', citations: [],
        error: { code: 'FIXTURE_ERROR', message: 'Synthetic relay error' } },
    walkthrough: { ...answered, trace_id: 'fixture-walkthrough', intent: 'walkthrough',
        walkthrough: { doc_id: 'SOP-114', revision: 'C', title: 'Synthetic bracket assembly', total: 3, index: 0,
            steps: [
                { step_id: '1', label: 'Seat', glance: 'Seat bracket on dowel pins.', body: 'Seat the bracket squarely on both dowel pins. Check alignment before inserting screws.' },
                { step_id: '2', label: 'Torque', glance: 'Torque M5 screws to 4 N-m.', body: 'Torque all four M5 screws to 4 N-m in a star pattern using a calibrated wrench. ' + 'Check each screw and mark it only after confirming torque. '.repeat(5) },
                { step_id: '3', label: 'Inspect', glance: 'Inspect and record completion.', body: 'Inspect bracket seating and torque marks. Record completion in the synthetic training log.' },
            ] } },
    logged: { ...answered, trace_id: 'fixture-logged', intent: 'deviation', outcome: 'logged', glance: 'Deviation logged.', body: 'Synthetic training deviation recorded.' },
};
export function taskFixture(now = Date.now()): Assignment {
    const steps = structuredClone(UI_FIXTURES.walkthrough.walkthrough!.steps);
    steps.push({ step_id: '4', label: 'Check', glance: 'Check the torque marks.', body: 'Check all four torque marks on the synthetic bracket.' }, { step_id: '5', label: 'Record', glance: 'Record completion.', body: 'Record completion of the synthetic training procedure.' });
    steps[0].warning = 'Disconnect the training rig before assembly.';
    steps[2].checkpoint = 'All four torque marks must be visible.';
    for (const index of [1, 2])
        steps[index].diagram = { diagram_id: `fixture-step-${index + 1}`, width: 576, height: 144, alt: 'Synthetic bracket torque order 1-4' };
    return { assignment_id: 'fixture-assignment-114', assigned_at: new Date(now).toISOString(), walkthrough: { doc_id: 'SOP-114', revision: 'C', title: 'Synthetic bracket assembly', total: 5, index: 0, steps, assignment_id: 'fixture-assignment-114' } };
}
