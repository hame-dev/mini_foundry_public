import { redirect } from "next/navigation";

// Spaces are an alias of Projects (there is no separate Space model).
export default function SpacesPage() {
  redirect("/workspace/projects");
}
