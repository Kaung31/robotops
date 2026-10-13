// Release wording for both pages, kept in one place so a launch build changes
// it once. The private candidate states that nothing is published or licensed.
export const RELEASE = {
  status: "Private release candidate · not published",
  datasetLicence: null as null | { name: string; href: string },
} as const;
export const REPOSITORY = "https://github.com/Kaung31/robotops";
