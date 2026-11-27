import {
  Activity,
  Bot,
  FileSearch,
  HeartPulse,
  History,
  LifeBuoy,
  Pill,
  ShieldCheck,
  Users,
} from 'lucide-react';

import DocumentIntelligencePage from './document-intelligence/DocumentIntelligencePage';
import MedicalTimelinePage from './unified-phr/MedicalTimelinePage';
import ClinicalSnapshotPage from './clinical-intelligence/ClinicalSnapshotPage';
import BiomarkerTrendsPage from './biomarker-analytics/BiomarkerTrendsPage';
import MedicationsPage from './medication-management/MedicationsPage';
import HolisticHealthPage from './holistic-health/HolisticHealthPage';
import FamilyHealthPage from './family-health/FamilyHealthPage';
import AssistancePage from './patient-assistance/AssistancePage';
import InsurancePage from './insurance-info/InsurancePage';

/**
 * Frontend Module Registry (Modules 01-09).
 *
 * Architecture rule:
 * - Navigation links and React Router routes are generated dynamically from this
 *   registry, filtered by both `enabled` and the signed-in user's `role`.
 * - To add a module later: create its folder under `src/modules/`, assign
 *   `component`, and flip `enabled: true`.
 */
export const MODULE_REGISTRY = [
  {
    id: 'document-intelligence',
    number: '01',
    title: 'Document Intelligence',
    category: 'Core',
    path: '/modules/document-intelligence',
    icon: FileSearch,
    roles: ['patient', 'doctor_navigator'],
    requiredScope: 'documents:write',
    enabled: true,
    component: DocumentIntelligencePage,
    description: 'OCR, AI classification, structured extraction, and Navigator Verify & Save.',
  },
  {
    id: 'unified-phr',
    number: '02',
    title: 'Medical Timeline',
    category: 'Core',
    path: '/modules/timeline',
    icon: History,
    roles: ['patient', 'doctor_navigator', 'family_member'],
    requiredScope: 'timeline:read',
    enabled: true,
    component: MedicalTimelinePage,
    description: 'Chronological personal health record, episode grouping, and search.',
  },
  {
    id: 'clinical-intelligence',
    number: '03',
    title: 'Clinical Snapshot',
    category: 'Core',
    path: '/modules/clinical-snapshot',
    icon: Bot,
    roles: ['patient', 'doctor_navigator', 'family_member'],
    requiredScope: 'summaries:read',
    enabled: true,
    component: ClinicalSnapshotPage,
    description: 'Grounded AI medical summary and 30-second clinical snapshot.',
  },
  {
    id: 'biomarker-analytics',
    number: '04',
    title: 'Biomarker Trends',
    category: 'High-value',
    path: '/modules/biomarkers',
    icon: Activity,
    roles: ['patient', 'doctor_navigator', 'family_member'],
    requiredScope: 'labs:read',
    enabled: true,
    component: BiomarkerTrendsPage,
    description: 'Unit-safe longitudinal Recharts graphs with lab reference ranges.',
  },
  {
    id: 'medication-management',
    number: '05',
    title: 'Medications',
    category: 'High-value',
    path: '/modules/medications',
    icon: Pill,
    roles: ['patient', 'doctor_navigator', 'family_member'],
    requiredScope: 'medications:read',
    enabled: true,
    component: MedicationsPage,
    description: 'Medication history, duplicate-molecule flags, and dose reminders.',
  },
  {
    id: 'holistic-health',
    number: '06',
    title: 'Holistic Health',
    category: 'Extension',
    path: '/modules/holistic',
    icon: HeartPulse,
    roles: ['patient', 'doctor_navigator'],
    requiredScope: 'holistic:read',
    enabled: true,
    component: HolisticHealthPage,
    description: 'Allopathy, Ayurveda/AYUSH, preventive, and wellness records.',
  },
  {
    id: 'family-health',
    number: '07',
    title: 'Family Health',
    category: 'Extension',
    path: '/modules/family',
    icon: Users,
    roles: ['patient', 'family_member'],
    requiredScope: 'all',
    enabled: true,
    component: FamilyHealthPage,
    description: 'Family profiles, explicit sharing permissions, and family overview.',
  },
  {
    id: 'patient-assistance',
    number: '08',
    title: 'Assistance & Emergency',
    category: 'Extension',
    path: '/modules/assistance',
    icon: LifeBuoy,
    roles: ['patient'],
    requiredScope: 'reminders:read',
    enabled: true,
    component: AssistancePage,
    description: 'Local-language & voice assistance, reminders, and nearby hospital map.',
  },
  {
    id: 'insurance-info',
    number: '09',
    title: 'Insurance & Expenses',
    category: 'Extension',
    path: '/modules/insurance',
    icon: ShieldCheck,
    roles: ['patient'],
    requiredScope: 'insurance:read',
    enabled: true,
    component: InsurancePage,
    description: 'Insurance policy records, Ayushman Bharat details, and expense logs.',
  },
];

export function getEnabledModulesForRole(role) {
  return MODULE_REGISTRY.filter((mod) => mod.enabled && mod.roles.includes(role) && mod.component);
}
