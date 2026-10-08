import PrototypeConsole from "./prototype-console";

// The prototype reads the variant from the URL at request time.
export const instant = false;

// Three radically different Host Console layouts, switchable with ?variant=A|B|C.
export default async function PrototypePage({
  searchParams,
}: {
  searchParams: Promise<{ variant?: string | string[] }>;
}) {
  const params = await searchParams;
  const value = Array.isArray(params.variant) ? params.variant[0] : params.variant;
  const initialVariant = value === "A" || value === "B" || value === "C" ? value : "A";
  return <PrototypeConsole initialVariant={initialVariant} />;
}
