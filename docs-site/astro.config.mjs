import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

export default defineConfig({
  site: "https://averyfreeman.github.io",
  base: "/codex-orchestrator-dashboard",
  integrations: [
    starlight({
      title: "Codex Orchestrator Dashboard",
      description: "Operator and maintainer guide for the self-hosted Codex fleet dashboard.",
      editLink: {
        baseUrl: "https://github.com/averyfreeman/codex-orchestrator-dashboard/edit/main/docs-site/",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/averyfreeman/codex-orchestrator-dashboard",
        },
      ],
      sidebar: [
        "index",
        {
          label: "Operator guide",
          items: [{ autogenerate: { directory: "operators" } }],
        },
        {
          label: "Maintainer guide",
          items: [{ autogenerate: { directory: "maintainers" } }],
        },
        {
          label: "Reference",
          items: [{ autogenerate: { directory: "reference" } }],
        },
      ],
    }),
  ],
});
