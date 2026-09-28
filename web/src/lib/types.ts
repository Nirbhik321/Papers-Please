// Shapes returned by the Papers Please API (server/main.py, server/analysis.py)

export type SubjectSummary = {
  code: string;
  name: string;
  branch: string;
  semester: number | null;
  paperCount: number;
  topicCount: number;
  minYear: number | null;
  maxYear: number | null;
  updatedAt: string | null;
};

export type CatalogEntry = {
  code: string;
  name: string;
  branch: string;
  semester: number | null;
};

export type Stats = { papers: number; subjects: number; updatedAt: string | null };

export type RecentPaper = { code: string; name: string; label: string; addedAt: string | null };

export type Session = {
  id: number;
  type: "see" | "model";
  source: "native" | "scanned" | null;
  label: string;
  short: string;
};

export type Wording = { session: number; where: string; marks: number | null; text: string };

export type Topic = {
  key: string;
  rank: number;
  label: string;
  text: string;
  frequency: number;
  frequencyPct: number;
  avgMarks: number;
  expectedMarks: number;
  sessions: number[];
  wordings: Wording[];
};

export type LadderStep = { rank: number; label: string; cumulative: number; full: boolean };

export type Module = { no: number; topics: Topic[]; ladder: LadderStep[]; fullAt: number | null };

export type SubjectData = {
  code: string;
  name: string;
  branch: string;
  semester: number | null;
  updatedAt: string;
  paperCount: number;
  topicCount: number;
  minYear: number | null;
  maxYear: number | null;
  moduleMarks: number;
  sessions: Session[];
  modules: Module[];
};

export type UploadStatus = {
  id: number;
  filename: string;
  status: "processing" | "awaiting_confirmation" | "review" | "approved" | "rejected" | "failed";
  stage: string;
  reason: string | null;
  detected: {
    subjectCode: string | null;
    subjectName: string | null;
    examYear: number | null;
    examMonth: string | null;
    paperType: "see" | "model";
  } | null;
  subjectCode: string | null;
  subjectName: string | null;
  examYear: number | null;
  examMonth: string | null;
  paperType: "see" | "model";
  pageCount: number | null;
  questionCount: number | null;
  modulesFound: number | null;
  preview: { module: number; where: string; marks: number | null; text: string }[];
};

export type AdminPaper = {
  id: number;
  filename: string;
  status: UploadStatus["status"];
  stage: string;
  reason: string | null;
  subjectCode: string | null;
  subjectName: string | null;
  examYear: number | null;
  examMonth: string | null;
  paperType: "see" | "model";
  session: string;
  pdfType: string | null;
  pageCount: number | null;
  questionCount: number | null;
  modulesFound: number | null;
  uploader: string | null;
  reviewedBy: string | null;
  createdAt: string | null;
};

export type AdminPaperDetail = AdminPaper & {
  detected: UploadStatus["detected"];
  questions: { module: number; where: string; marks: number | null; text: string }[];
  comparison: {
    against: AdminPaper;
    score: number;
    pairs: { a: { where: string; text: string }; b: { where: string; text: string }; similarity: number }[];
  } | null;
};
