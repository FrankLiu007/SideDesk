import { api, type Project } from '$lib/api';

export const desk = $state({
	projects: [] as Project[],
	activeId: 0,
	ready: false,
	token: 0
});

export async function refreshProjects() {
	try {
		const rows = await api.projects();
		desk.projects = rows;
		desk.activeId = rows.find((item) => item.active)?.id ?? rows[0]?.id ?? 0;
	} finally {
		desk.ready = true;
		desk.token += 1;
	}
}

export async function activateProject(id: number) {
	if (!id || id === desk.activeId) return;
	await api.activateProject(id);
	await refreshProjects();
}
