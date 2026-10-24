"""Create the required implementation PDF from verified live results only."""
from pathlib import Path
from collections import defaultdict
import csv
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.graphics.shapes import Drawing, Rect, Line, String

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'
EV=OUT/'evaluation'


def main():
    audit=json.loads((EV/'audit.json').read_text())
    matrix=json.loads((OUT/'live'/'matrix.json').read_text())
    trained=json.loads((OUT/'trained_model.json').read_text())
    learning=json.loads((OUT/'training_evaluation.json').read_text())
    recorded=json.loads((EV/'recorded_training.json').read_text())
    calibration=json.loads((OUT/'live'/'calibration-kubernetes.json').read_text())
    faults=json.loads((EV/'fault_checks.json').read_text())
    rows=audit['results']
    lookup={(r['scenario'],r['policy']):r for r in rows}
    # Calibration figure uses all repeats, including unsuccessful points.
    points=defaultdict(list)
    for item in calibration['points']:
        points[item['rate_rps']].append(item['p95_ms'])
    fig,ax=plt.subplots(figsize=(8.5,3.4))
    for rate,values in sorted(points.items()):
        mean=float(np.mean(values))
        ax.errorbar(rate,mean,yerr=[[mean-min(values)],[max(values)-mean]],fmt='o',capsize=4,color='#008d83')
    ax.axhline(250,color='#ad3535',ls='--',label='250 ms target')
    ax.axvline(calibration['recommended_safe_rps'],color='#bd7033',ls=':',label='Selected safe rate (14.4 RPS)')
    ax.set(xlabel='One-pod target offered RPS',ylabel='Measured run p95 (ms, log scale)',yscale='log',title='Measured per-replica latency envelope (250m CPU limit)')
    ax.legend(fontsize=9);ax.grid(alpha=.15);fig.tight_layout();fig.savefig(EV/'calibration.png',dpi=170);plt.close(fig)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Cover',fontName='Helvetica-Bold',fontSize=23,leading=28,spaceAfter=14,textColor=colors.HexColor('#143148')))
    styles.add(ParagraphStyle(name='H',fontName='Helvetica-Bold',fontSize=16,leading=20,spaceAfter=11,textColor=colors.HexColor('#006f79')))
    styles.add(ParagraphStyle(name='Sub',fontName='Helvetica-Bold',fontSize=12,leading=16,spaceBefore=10,spaceAfter=6,textColor=colors.HexColor('#143148')))
    styles.add(ParagraphStyle(name='B',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=8,textColor=colors.HexColor('#243747')))
    styles.add(ParagraphStyle(name='S',fontName='Helvetica',fontSize=8.5,leading=11.5,spaceAfter=6,textColor=colors.HexColor('#425c6e')))
    story=[]
    def p(text,style='B'):story.append(Paragraph(text,styles[style]))
    def h(text):p(text,'Sub')
    def page(number,title):
        if story:story.append(PageBreak())
        p(f'ACC LAB-CA | IMPLEMENTATION REPORT | {number:02d}','S');p(title,'H')
    def table(data,widths):
        t=Table([[Paragraph(str(x),styles['S']) for x in row] for row in data],colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f3f4')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d7e4e9'))]))
        story.append(t)
    def img(path,width=500):
        from PIL import Image as PIL
        with PIL.open(path) as image: w,h=image.size
        story.append(Image(str(path),width=width,height=width*h/w))
    page(1,'ML-Based Predictive Cloud Resource Management')
    p('With SLA-Aware Auto-Scaling, Cost Optimization, and Adaptive Workload Handling','Cover')
    table([['Student','Roll number'],['Parth Dhande','16010123232'],['Purab Madhan','16010123242'],['Pushkar Rai','16010123243']],[300,200])
    h('Abstract')
    p('We implemented and demonstrated a workload predictor and resource controller for a real CPU-bound HTTP service on a local Kubernetes cluster. The controller forecasts near-future request demand, adjusts application replicas, and combines prediction with observed-demand and latency safeguards. Controlled synthetic traffic is replayed as actual HTTP requests; latency, errors, worker CPU and replica changes are measured.')
    p('Evaluation compares fixed maximum capacity, custom reactive scaling and guarded predictive scaling on identical arrival schedules, with two independent seeds per workload. We report both performance and resource overhead, rather than assuming prediction is universally superior. Infrastructure cost and energy are transparent analytical proxies; they are not measured cloud bills or physical energy savings.')
    h('Scope and implementation status')
    p(f"The comparison suite contains <b>{audit['complete_runs']} completed Kubernetes runs</b>. A trained Ridge model, raw request records, decision logs, resource timelines and reproducible commands accompany the code. The implementation scales application pods on one laptop, not physical nodes or an AWS Auto Scaling group.")
    p('Submission repository: <link href="https://github.com/parth1056/accml">github.com/parth1056/accml</link><br/>Default branch: parth/predictive-scaler. Code baseline: 3c87760. Prepared from execution on 24 October 2026.','S')
    page(2,'Architecture and execution platform')
    diagram=Drawing(500,145)
    for x,y,label in [(0,88,'Open-loop load'),(175,88,'HTTP gateway'),(350,88,'Worker pods'),(0,8,'Completed windows'),(175,8,'Ridge + policy'),(350,8,'Deployment scale')]:
        diagram.add(Rect(x,y,145,40,rx=5,fillColor=colors.HexColor('#e9f3f4'),strokeColor=colors.HexColor('#92bdc7')))
        diagram.add(String(x+72.5,y+16,label,textAnchor='middle',fontName='Helvetica-Bold',fontSize=10))
    for x1,y1,x2,y2 in [(145,108,175,108),(320,108,350,108),(72,88,72,48),(145,28,175,28),(320,28,350,28),(423,48,423,88)]:diagram.add(Line(x1,y1,x2,y2,strokeColor=colors.HexColor('#007d85')))
    story.append(diagram)
    p('The host runs the traffic generator and controller. Requests reach one gateway pod through a local port-forward. The gateway opens a new connection to the worker Service for each request, allowing Kubernetes to distribute traffic across Ready endpoints. Scaling commands target only the dedicated acc-lab context/namespace. A local API proxy supplies pod state and sampled worker CPU metrics.')
    table([['Component','Implementation'],['Platform','Docker Desktop Linux engine; single-node Minikube, Kubernetes v1.34.0; preloaded application image.'],['CPU task','PBKDF2-HMAC-SHA256, fixed 60,000 iterations/request; one active task per worker with a bounded asynchronous queue.'],['Resource envelope','Each worker requests/limits 250m CPU; 32 MiB memory request and 96 MiB limit. Primary comparisons allow 1-4 worker replicas.'],['Readiness/draining','Configured five-second readiness delay, identical for all policies; pre-stop delay and graceful drain reduce interrupted in-flight work.'],['Application interface','/work, /health, /ready and /metrics. Gateway and experiment viewer expose only local host connections.']],[110,390])
    p('All replicas share the same physical host. Pod scaling redistributes a fixed host resource pool; reductions in allocated pods do not power off the laptop. The source includes a real-process backend for development, but the main comparison results in this report use Kubernetes.','S')
    page(3,'Input data, features and ML training')
    p('Incoming demand is offered requests/second, counted from actual generator send timestamps in completed ten-second windows. Completed throughput is not used as demand because overload could suppress completions. The generator follows a seeded open-loop arrival schedule and records send lag, status and end-to-end latency for every request.')
    table([['Item','Definition'],['Features (10)','Six completed RPS windows; trailing mean, standard deviation and maximum; short trend (latest minus oldest)/5.'],['Target','Maximum offered RPS across the next three ten-second windows: a 30-second provisioning horizon.'],['Algorithm','Standardized Ridge regression with an unpenalized intercept; negative predictions are clipped to zero.'],['Data separation',f"{learning['training_rows']} training rows from seeds 0-11; {learning['validation_rows']} validation rows from seeds 50-55; independent synthetic holdout seed 99. No labels cross sequence boundaries."],['Selection',f"Validation selects alpha={trained['alpha']} from 1, 10 and 100. A validation positive-residual 90th percentile supplies empirical headroom, not guaranteed interval coverage."],['Inference','The saved JSON coefficients are reused for matching capacity/horizon settings. This is offline training followed by online prediction, not continuous retraining.']],[105,395])
    p(f"On the separate synthetic holdout, Ridge MAE was <b>{learning['test_mae_rps']:.2f} RPS</b> and RMSE <b>{learning['test_rmse_rps']:.2f} RPS</b>, versus persistence MAE <b>{learning['persistence_test_mae_rps']:.2f} RPS</b>. These are model-only synthetic results; real HTTP replay results are evaluated separately.")
    img(OUT/'trained_forecast.png')
    p('No future phase labels, scenario ID or scripted surge times are supplied to the predictor. The synthetic training family includes varied cycles, amplitudes and noise. It is controllable experimental data, not a production workload trace.','S')
    p(f"A separate recorded-replay candidate was subsequently trained on {recorded['training_rows']} measured-demand rows (seed 101), validated on {recorded['validation_rows']} rows (202), and tested on {recorded['test_rows']} independent rows (404). Its held-out MAE was {recorded['candidate_test_mae_rps']:.2f} RPS versus {recorded['primary_test_mae_rps']:.2f} for the original model and {recorded['persistence_test_mae_rps']:.2f} for persistence. This small exploratory candidate was not substituted into the completed 12-run benchmark; its weights and provenance are saved separately.",'S')
    page(4,'Measured capacity and provisioning delay')
    p('We first measured one replica at increasing offered rates under the fixed 250m CPU limit. A rate passes only if every retained repeat meets global and nonempty-window p95 <=250 ms, successful responses >=99%, and the load generator remains valid. We select 80% of the highest repeatably passing rate as safe per-replica capacity.')
    img(EV/'calibration.png')
    table([['Measurement','Observed outcome'],['18 RPS / one pod','Repeated passing runs; p95 approximately 103-109 ms and no failed requests.'],['24 RPS / one pod','Near the latency boundary; one repeat has violating windows despite global p95 below 250 ms. Not selected as repeatably safe.'],['30 RPS / one pod','CPU saturation; p95 about 1.5 s and approximately 2.63% failed requests.'],['Selected safe capacity',f"{calibration['recommended_safe_rps']:.1f} RPS per replica (0.8 x 18 RPS)."],['Capacity check','Two pods at 28.8 target RPS: p95 about 68 ms. Four pods at 57.6 target RPS: p95 about 110 ms. Both had 100% successful scored requests.']],[130,370])
    p(f"Across sampled scale-ups, window-end-to-Ready delay had median {audit['sampled_window_end_to_ready_median_s']:.1f} s and p95 {audit['sampled_window_end_to_ready_p95_s']:.1f} s. This includes decision/proxy latency and approximately one-second sampling granularity; it is not an exact boot-time measurement. The 30-second forecast horizon covers the observed provisioning delay.",'S')
    page(5,'Resource allocation and safety mechanism')
    p('<b>Forecast requirement:</b> ceil((predicted next-30s peak + validation buffer) / safe_rps).<br/><b>Observed requirement:</b> ceil(measured offered RPS / safe_rps).<br/>The guarded controller selects the larger bounded requirement. With monotonically increasing capacity/cost, this chooses the smallest integer allocation covering that demand estimate; it is not a global optimization or reinforcement-learning algorithm.')
    table([['Situation','Decision'],['Rising forecast','Request additional replicas immediately; distinguish desired, Ready and pending capacity. Do not treat pending pods as serving traffic.'],['Underprediction','Observed demand can override the forecast. If p95 exceeds 250 ms or error fraction exceeds 1%, request a bounded extra replica when no scale-out is pending.'],['Overprediction / falling load','Keep the maximum recommendation in the 30-second stabilization window; remove at most one replica per decision. Pending scale-outs block downscale.'],['Caps / budget','Clamp desired count to hardware maximum and any configured rate-budget cap. CAPACITY_LIMITED records an infeasible demand estimate; the controller cannot guarantee both the cap and the SLA.'],['Delayed/stale decision','The policy holds capacity when telemetry is marked stale. Unit tests exercise this guard. In the harness, live freshness is based on completed-window/decision lag; this is not a production monitoring-failure detector.'],['Failure handling','Actuation errors are recorded rather than treated as successful changes. Aborted experiments stop their generator, preserve available raw logs, and return the lab fleet to one replica.']],[130,370])
    h('Why stability matters')
    p('Readiness delay makes repeated blind scale-out requests wasteful. Immediate scale-down can also remove capacity just before a forecasted rise or while requests remain in flight. Common stabilization rules are applied to the dynamic baselines so the comparison does not falsely attribute all stability benefits to ML.')
    h('Unit and integration checks')
    p('Thirteen checks cover future-label/past-feature separation, repeatable seeds, saved-model equivalence, hard budget bounds, stale-metric hold, stabilization under clock jitter, pending-capacity handling, a real HTTP hash/CPU endpoint, and Kubernetes chunked JSON handling. These checks complement actual cluster runs; they do not replace performance measurements.')
    page(6,'Matched experiment design')
    table([['Dimension','Frozen comparison setting'],['Policies','Fixed maximum (4 pods), custom reactive scaling, guarded predictive scaling. The reactive baseline is not Kubernetes HPA.'],['Workloads','Periodic demand and an unseen flash-crowd addition. Arrivals are synthetic seeded Poisson schedules, replayed as real HTTP traffic.'],['Repeats','Two independent seeds (101, 202) per scenario/policy: 12 sequential runs. A saved seed randomizes policy run order.'],['Scoring','240-second run, first 60 seconds excluded as common model/controller warm-up; 180 scored seconds/run. Warm-up remains in raw logs.'],['Fairness','Same worker image, CPU task, CPU/memory limits, min/max replicas, ten-second control interval and stabilization settings. Each run resets to one Ready worker.'],['Generator checks','Raw planned versus actual sends, p99 scheduling lag, request status and bounded client concurrency. A generator-capacity drop invalidates a run.'],['Audit',f"{audit['matched_schedules']} scenario/seed schedule groups match byte-for-byte across policies; all 12 runs use identical model and source fingerprints."]],[115,385])
    p('Latency statistics use raw successful-request timings; failures/timeouts are reported separately so a low successful-only p95 cannot hide errors. SLA-window violations combine the latency target with the 99% success condition. We do not average window percentiles to calculate run p95.')
    p('Allocated replica-seconds integrate actual pod allocation, including warming and terminating pods. Worker CPU is sampled from process CPU counters and normalized by the configured CPU limit. Constant gateway/node overhead is outside the worker-only resource comparison.')
    p('Cost = replica-hours x 0.02 illustrative currency units per replica-hour. Energy proxy = integral of 10 W per allocated replica plus 20 W per measured CPU core used, converted to Wh. Neither quantity represents actual AWS billing or physically measured energy; a shared host may consume similar wall power despite fewer pods.')
    p('Source SHA-256: '+audit['source_sha256']+'<br/>Saved-model SHA-256: '+audit['model_sha256'],'S')
    page(7,'Measured comparison results')
    table([['Scenario / policy','Run p95 range (ms)','Replica-s mean','SLA windows mean'],*[ [r['scenario']+' / '+r['policy'].replace('_',' '),f"{r['p95_min_ms']:.1f}-{r['p95_max_ms']:.1f}",f"{r['mean_replica_seconds']:.1f}",f"{100*r['mean_sla_violating_window_fraction']:.1f}%"] for r in rows]],[175,110,100,115])
    img(EV/'comparison.png')
    p('Whiskers show the observed minimum/maximum over two repeats, not a statistical confidence interval. The plotted latency bar is the mean of run p95 values, explicitly separate from any pooled-request percentile. Two repeats are sufficient for a lab comparison, not a production generalization claim.','S')
    page(8,'Utilization, estimated cost and energy')
    table([['Scenario / policy','Mean CPU use / limit','Mean replica-s','Estimated cost','Energy proxy Wh'],
        *[[r['scenario']+' / '+r['policy'].replace('_',' '),f"{100*r['mean_worker_cpu_utilization']:.1f}%",
           f"{r['mean_replica_seconds']:.1f}",f"{r['mean_estimated_cost']:.5f}",f"{r['mean_energy_proxy_wh']:.3f}"] for r in rows]],
        [170,85,80,85,80])
    p('CPU utilization is sampled worker process CPU time divided by allocated worker CPU-limit time (250m per pod). It excludes the gateway and Kubernetes system processes. More allocated headroom can lower utilization while protecting tail latency; maximum utilization is not itself the optimization objective.')
    p('Cost is in illustrative currency units, using 0.02 units/replica-hour for all policies. Only worker allocation is compared; constant platform overhead is excluded. The energy proxy assumes 10 W per allocated replica plus 20 W per measured CPU core used. These assumptions are not EC2 prices, physical host power, or actual energy savings.')
    h('Sensitivity to assumed idle power')
    sensitivity=[]
    for r in rows:
        selected=[item['summary'] for item in matrix['completed'] if item['summary']['scenario']==r['scenario'] and item['summary']['policy']==r['policy']]
        cpu=float(np.mean([s['measured_worker_cpu_seconds'] for s in selected]))
        energy=lambda idle:(idle*r['mean_replica_seconds']+20*cpu)/3600
        sensitivity.append([r['scenario']+' / '+r['policy'].replace('_',' '),f'{energy(0):.3f}',f'{energy(5):.3f}',f'{energy(20):.3f}'])
    table([['Scenario / policy','0 W idle (Wh)','5 W idle (Wh)','20 W idle (Wh)'],*sensitivity],[200,100,100,100])
    p('With zero assumed idle power, the proxy mainly reflects the similar CPU work completed by each policy, and differences shrink. With a higher idle term, fewer allocated replicas appear more favorable. This is sensitivity analysis of a model, not a measurement of the laptop\'s wall power.','S')
    page(9,'Trade-offs, prediction error and limitations')
    for scenario in ('periodic','flash'):
        fixed=lookup[(scenario,'fixed')];reactive=lookup[(scenario,'reactive')];guarded=lookup[(scenario,'guarded_predictive')]
        saving=100*(1-guarded['mean_replica_seconds']/fixed['mean_replica_seconds'])
        overhead=100*(guarded['mean_replica_seconds']/reactive['mean_replica_seconds']-1)
        h(scenario.title()+' workload')
        p(f"Guarded prediction used {saving:.1f}% fewer worker replica-seconds than fixed maximum capacity, but {overhead:.1f}% more than the reactive baseline. Its run p95 range was {guarded['p95_min_ms']:.1f}-{guarded['p95_max_ms']:.1f} ms; reactive was {reactive['p95_min_ms']:.1f}-{reactive['p95_max_ms']:.1f} ms. These measurements expose the cost/performance trade-off rather than establish a universal winner.")
        p(f"The operating predictor's mean MAE was {guarded['mean_forecast_mae_rps']:.2f} RPS, versus persistence {guarded['mean_persistence_mae_rps']:.2f} RPS. Synthetic holdout accuracy alone therefore does not establish superior forecasting during real replay.")
    h('When the prediction is wrong')
    p('An unseen burst cannot reliably be predicted from a history that contains no warning. The observed-demand/latency path can request more capacity, but pod readiness delay still permits temporary harm. Overprediction consumes extra replica-time until stabilization allows downscale. A hard cap can make the latency goal infeasible; the correct response is to expose that conflict, not claim an unconditional SLA guarantee.')
    h('Energy and cost sensitivity')
    p('The energy proxy weights allocated idle capacity and actual CPU separately. Changing assumed idle watts changes the apparent benefit of fewer replicas; removing the idle term greatly reduces that benefit because the same CPU work still executes. No physical energy reduction or cloud-bill saving is inferred from this local experiment.')
    h('Limits and next improvements')
    p('The workload is synthetic, training is offline, and all replicas share one laptop. Only two test seeds are used. Host contention, Service routing and readiness sampling affect variability. Future work would validate on independent production traces, recalibrate after deployment changes, improve uncertainty estimation, and test a real cloud billing/energy environment. These are future extensions, not implemented claims.')
    page(10,'Deliberate prediction failure and a hard budget')
    zero=faults['results'][:2]
    table([['Injected condition / policy','Run p95 ms','Failed requests','SLA windows'],
        *[[r['summary']['scenario']+' / '+r['summary']['policy'].replace('_',' '),
           f"{r['summary']['p95_ms']:.1f}",f"{100*r['summary']['failure_fraction']:.2f}%",
           f"{100*r['summary']['sla_violating_window_fraction']:.1f}%"] for r in faults['results']]],
        [225,80,95,100])
    p('The zero-forecast pair deliberately multiplies the predictor output by zero while replaying the same periodic arrival schedule (seed 404). This is a controlled model-failure injection, not a claim about naturally observed model accuracy. We compare the forecast-only ablation against the guarded policy; both retain common readiness, replica limits and stabilization. One run per policy is used for this mechanism demonstration.')
    fault_by_policy={r['summary']['policy']:r['summary'] for r in zero}
    plain=fault_by_policy['plain_predictive'];protected=fault_by_policy['guarded_predictive']
    p(f"In this paired injection, forecast-only control failed {100*plain['failure_fraction']:.2f}% of requests with p95 {plain['p95_ms']:.0f} ms. Guarded control failed {100*protected['failure_fraction']:.2f}% with p95 {protected['p95_ms']:.0f} ms. Its violating-window rate was still {100*protected['sla_violating_window_fraction']:.1f}%, demonstrating that rescue cannot remove readiness delay.",'S')
    fig,axes=plt.subplots(2,1,figsize=(8.5,4.3),sharex=True)
    for item in zero:
        directory=OUT/'live'/str(item['directory']).replace('\\','/').rsplit('/',1)[-1];s=item['summary']
        with (directory/'requests.csv').open() as f:records=list(csv.DictReader(f))
        with (directory/'resources.csv').open() as f:resources=list(csv.DictReader(f))
        label='Guarded, zero forecast' if s['policy']=='guarded_predictive' else 'Forecast only, zero forecast'
        color='#008d83' if s['policy']=='guarded_predictive' else '#b9642d'
        ts=[];lat=[]
        for left in range(0,240,10):
            values=[float(r['latency_ms']) for r in records if left<=float(r['sent_s'])<left+10 and int(r['status'])==200]
            ts.append(left+10);lat.append(np.percentile(values,95) if values else np.nan)
        axes[0].plot(ts,lat,label=label,color=color)
        axes[1].step([float(r['elapsed_s']) for r in resources],[int(r['ready']) for r in resources],where='post',color=color)
    axes[0].axhline(250,color='#a63333',ls='--',label='250 ms target')
    axes[0].set(ylabel='Measured p95 (ms)',yscale='log');axes[0].legend(fontsize=9)
    axes[1].set(ylabel='Ready replicas',xlabel='Actual elapsed seconds')
    for ax in axes:ax.axvspan(0,60,color='#dfe6ed',alpha=.5);ax.grid(alpha=.15)
    fig.tight_layout();fig.savefig(EV/'fault_checks.png',dpi=170);plt.close(fig)
    img(EV/'fault_checks.png')
    p('The separate budget stress test uses a different seed (505), a 120-second run and a rate budget of 0.02 units/hour at 0.02 units/replica-hour, limiting desired capacity to one replica. Its outcome demonstrates the budget/SLA conflict; it is not a paired performance comparison against the zero-forecast runs. A resource ceiling must be exposed when it prevents sufficient provisioning.','S')
    page(11,'Execution screenshots: failed forecast and rescue')
    img(OUT/'evidence'/'zero_forecast_plain.png')
    p('Forecast-only ablation during the real zero-output injection: the model output is zero while actual incoming requests continue. The resource controller retains its minimum allocation. Measured failure and latency totals are reported on the preceding page.','S')
    story.append(Spacer(1,8))
    img(OUT/'evidence'/'zero_forecast_guarded.png')
    p('Guarded policy under the same injected condition: observed demand and latency can request capacity independently of the zero forecast. This screenshot records a real rescue transition; temporary latency harm remains visible in the full raw timeline.','S')
    page(12,'Execution evidence and reproduction')
    img(OUT/'evidence'/'kubernetes_live_view.png')
    p('Actual application viewer during a Kubernetes run: real desired/Ready replicas, measured offered RPS and latency, and the model forecast at issue time. This is execution evidence, not a simulated capacity plot. The raw deployment listing is preserved in output/evidence/kubernetes_state.txt.','S')
    h('Reproduction')
    p('1. Install requirements; run SetupLab.ps1.<br/>2. Calibrate the current machine and train the saved model at its safe rate.<br/>3. Run scaler.matrix for matched experiments, then tools/evaluate_matrix.py.<br/>4. Inspect per-run requests.csv, decisions.csv, resources.csv, model.json and summary.json.<br/>5. Run scaler.viewer for the read-only live/result display. README contains exact commands.')
    h('References')
    p('Course Lab-CA assignment and submission rubric, supplied October 2026.<br/><link href="https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/">Kubernetes: Horizontal Pod Autoscaling</link> (background; our reactive baseline is custom).<br/><link href="https://minikube.sigs.k8s.io/docs/drivers/docker/">Minikube: Docker driver</link>.<br/><link href="https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html">scikit-learn: Lagged features for time-series forecasting</link> (causal evaluation guidance; our Ridge implementation uses NumPy).','S')
    def footer(canvas,doc):
        canvas.setCreator('Parth Dhande, Purab Madhan, Pushkar Rai')
        canvas.setStrokeColor(colors.HexColor('#d5e1e7'));canvas.line(42,39,A4[0]-42,39)
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#536d7c'))
        canvas.drawString(42,25,'ACC LAB-CA | LOCAL KUBERNETES IMPLEMENTATION | 24 OCTOBER 2026')
        canvas.drawRightString(A4[0]-42,25,str(doc.page))
    target=OUT/'ACC_Lab_CA_Implementation_Report.pdf'
    SimpleDocTemplate(str(target),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=38,bottomMargin=52,
        title='ACC Lab-CA: Predictive Cloud Resource Management - Implementation Report',
        author='Parth Dhande, Purab Madhan, Pushkar Rai').build(story,onFirstPage=footer,onLaterPages=footer)
    print(target)


if __name__=='__main__':main()
