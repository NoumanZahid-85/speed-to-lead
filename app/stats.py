from fastapi import APIRouter
from app.repository import LeadRepository, InMemoryLeadRepository

router = APIRouter()


@router.get("/stats")
async def get_stats():
    repo = await LeadRepository.get_instance()
    stats = await repo.get_stats()
    
    counts = stats.get("by_status", {})
    total_leads = sum(counts.values())

    return {
        "total_leads": total_leads,
        "by_status": counts,
        "avg_elapsed_seconds": stats.get("avg_elapsed_seconds"),
        "oldest_unresolved": stats.get("oldest_unresolved"),
    }


@router.get("/leads")
async def get_leads():
    repo = await LeadRepository.get_instance()
    if isinstance(repo, InMemoryLeadRepository):
        # Return serializable copy
        leads_list = []
        for lead in repo._leads.values():
            lead_copy = lead.copy()
            if lead_copy.get("created_at"):
                lead_copy["created_at"] = str(lead_copy["created_at"])
            if lead_copy.get("updated_at"):
                lead_copy["updated_at"] = str(lead_copy["updated_at"])
            leads_list.append(lead_copy)
        return leads_list
    else:
        rows = await repo.pool.fetch("SELECT * FROM leads ORDER BY created_at DESC")
        leads_list = []
        for r in rows:
            lead_copy = dict(r)
            if lead_copy.get("created_at"):
                lead_copy["created_at"] = str(lead_copy["created_at"])
            if lead_copy.get("updated_at"):
                lead_copy["updated_at"] = str(lead_copy["updated_at"])
            leads_list.append(lead_copy)
        return leads_list