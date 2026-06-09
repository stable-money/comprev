import { JobProgress } from "@/components/job-progress";

export default async function JobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <JobProgress jobId={jobId} />;
}
