import type { Metadata } from "next";
import { Suspense } from "react";
import { getCatalog } from "@/lib/api";
import { UploadClient } from "./UploadClient";

export const revalidate = 3600;

export const metadata: Metadata = {
  title: "Upload a question paper",
  description: "Add a past VTU question paper to the shared bank. Every upload is checked before it changes any subject.",
};

export default async function UploadPage() {
  const catalog = await getCatalog();
  return (
    <Suspense>
      <UploadClient catalog={catalog} />
    </Suspense>
  );
}
