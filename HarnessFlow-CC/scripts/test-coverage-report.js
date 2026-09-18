#!/usr/bin/env node

const fs = require('fs');

const TASKS_FILE = 'docs/harnessflow/03_TASKS.json';
const REQUIREMENTS_FILE = 'docs/harnessflow/00_REQUIREMENTS.md';

function readInput() {
  const tasksDocument = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf-8'));
  const requirements = fs.readFileSync(REQUIREMENTS_FILE, 'utf-8');
  const tasks = (tasksDocument.tasks || tasksDocument.phases?.flatMap((phase) =>
    phase.batches.flatMap((batch) => batch.tasks || [])
  ) || []);
  const requirementsIds = [...new Set(requirements.match(/\b(?:REQ|R)-\d+\b/g) || [])];
  return { tasks, requirementsIds };
}

function generateReport() {
  const { tasks, requirementsIds } = readInput();
  const coverage = Object.fromEntries(requirementsIds.map((requirementId) => [
    requirementId,
    { unit: false, integration: false, e2e: false, ui: false, tasks: [] },
  ]));

  tasks.forEach((task) => {
    if (!task.coverage_matrix) return;
    Object.entries(task.coverage_matrix).forEach(([requirementId, matrix]) => {
      if (!coverage[requirementId]) return;
      coverage[requirementId].unit ||= matrix.unit;
      coverage[requirementId].integration ||= matrix.integration;
      coverage[requirementId].e2e ||= matrix.e2e;
      coverage[requirementId].ui ||= matrix.ui;
      coverage[requirementId].tasks.push(task.id);
    });
  });

  tasks.forEach((task) => {
    const interactiveTests = task.tests?.ui_interactive || [];
    const interactiveRequirements = new Set(interactiveTests.flatMap((test) => test.covers || []));
    Object.entries(task.coverage_matrix || {}).forEach(([requirementId, matrix]) => {
      if (!coverage[requirementId]) return;
      coverage[requirementId].ui ||= Boolean(matrix.ui && interactiveRequirements.has(requirementId));
    });
  });

  console.log('\n📊 Test Coverage Matrix Report\n');
  console.log('| Requirement | Unit | Integration | E2E | UI | Confidence | Tasks |');
  console.log('|-------------|------|-------------|-----|----|------------|-------|');

  requirementsIds.forEach((requirementId) => {
    const requirement = coverage[requirementId];
    const layers = [requirement.unit, requirement.integration, requirement.e2e, requirement.ui].filter(Boolean).length;
    const confidence = layers === 3 ? 'HIGH' : layers === 2 ? 'MEDIUM' : 'LOW';
    const unit = requirement.unit ? '✅' : '❌';
    const integration = requirement.integration ? '✅' : '❌';
    const e2e = requirement.e2e ? '✅' : '❌';
    const ui = requirement.ui ? '✅' : '❌';
    const tasksText = requirement.tasks.join(', ') || 'none';
    console.log(`| ${requirementId} | ${unit} | ${integration} | ${e2e} | ${ui} | ${confidence} | ${tasksText} |`);
  });

  const lowConfidence = requirementsIds.filter((requirementId) => {
    const requirement = coverage[requirementId];
    return [requirement.unit, requirement.integration, requirement.e2e, requirement.ui].filter(Boolean).length === 1;
  });

  if (lowConfidence.length > 0) {
    console.log(`\n⚠️  ${lowConfidence.length} requirements have LOW confidence (single layer)`);
  }
}

generateReport();
