from typing import Dict, Any, Optional
import os

def get_agent_functions(work_dir: Optional[str] = None) -> Dict[str, Any]:
    """Get the agent functions with the correct work directory configuration."""
    from finrobot.functional import (
        ReportAnalysisUtils, MplFinanceUtils, ReportChartUtils,
        CodingUtils, BackTraderUtils, ReportLabUtils, TextUtils,
        get_rag_function
    )
    
    # Initialize utilities with work directory
    report_analysis = ReportAnalysisUtils(work_dir=work_dir)
    chart_utils = ReportChartUtils(work_dir=work_dir)
    mpl_finance = MplFinanceUtils(work_dir=work_dir)
    coding_utils = CodingUtils(work_dir=work_dir)
    backtrader = BackTraderUtils(work_dir=work_dir)
    report_lab = ReportLabUtils(work_dir=work_dir)
    text_utils = TextUtils(work_dir=work_dir)
    
    return {
        "analyze_balance_sheet": report_analysis.analyze_balance_sheet,
        "analyze_income_stmt": report_analysis.analyze_income_stmt,
        "analyze_cash_flow": report_analysis.analyze_cash_flow,
        "get_risk_assessment": report_analysis.get_risk_assessment,
        "get_key_data": report_analysis.get_key_data,
        "get_share_performance": chart_utils.get_share_performance,
        "get_pe_eps_performance": chart_utils.get_pe_eps_performance,
        "plot_stock_price_chart": mpl_finance.plot_stock_price_chart,
        "create_file_with_code": coding_utils.create_file_with_code,
        "back_test": backtrader.back_test,
        "build_annual_report": report_lab.build_annual_report,
        "check_text_length": text_utils.check_text_length,
        "get_rag": get_rag_function,
    } 