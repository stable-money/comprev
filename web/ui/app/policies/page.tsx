import { fetchChecks, fetchPolicyFiles } from "@/lib/api";
import { PoliciesView } from "@/components/policies-view";

export const dynamic = "force-dynamic";

export default async function PoliciesPage() {
  const [policyFiles, checks] = await Promise.all([
    fetchPolicyFiles(),
    fetchChecks(),
  ]);

  return (
    <div className="space-y-8">
      {/* Notion-style page header: emoji icon, big title, lede */}
      <header className="space-y-3">
        <div className="text-5xl leading-none">🛡️</div>
        <h1 className="text-[2.5rem] font-bold leading-tight tracking-tight">
          Policies
        </h1>
        <p className="text-muted-foreground max-w-xl text-base leading-relaxed">
          The configuration files and checks used to review every upload. Open a
          file to read its contents, or a check for its full definition.
        </p>
      </header>

      <PoliciesView policyFiles={policyFiles} checks={checks} />
    </div>
  );
}
