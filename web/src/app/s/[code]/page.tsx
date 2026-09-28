import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { getSubject, getSubjects, NotFound } from "@/lib/api";
import type { SubjectData } from "@/lib/types";
import { SubjectView } from "./SubjectView";

export const revalidate = 300;

export async function generateStaticParams() {
  const subjects = await getSubjects();
  return subjects.map((s) => ({ code: s.code }));
}

async function load(code: string): Promise<SubjectData> {
  try {
    const data = await getSubject(code);
    if (!data) notFound();
    return data;
  } catch (err) {
    if (err instanceof NotFound) notFound();
    throw err;
  }
}

export async function generateMetadata(props: PageProps<"/s/[code]">): Promise<Metadata> {
  const { code } = await props.params;
  try {
    const data = await getSubject(code.toUpperCase());
    if (!data) return {};
    return {
      title: `${data.code} ${data.name} — most repeated questions`,
      description: `${data.topicCount} topics from ${data.paperCount} past VTU papers for ${data.code} ${data.name}, ranked by how often they repeat, with a printable cheat sheet.`,
    };
  } catch {
    return {};
  }
}

export default async function SubjectPage(props: PageProps<"/s/[code]">) {
  const { code } = await props.params;
  if (code !== code.toUpperCase()) permanentRedirect(`/s/${code.toUpperCase()}`);
  const data = await load(code);
  return <SubjectView data={data} />;
}
