# References

Full list of the sources behind the model, the numerical methods, the data and the software. Short versions appear in the README, the notebook (§8) and the web demo.

## Race strategy and motorsport simulation

1. A. Heilmeier, M. Graf, J. Betz and M. Lienkamp, "Application of Monte Carlo methods to consider probabilistic effects in a race simulation for circuit motorsport," *Applied Sciences*, vol. 10, no. 12, art. 4229, 2020. doi: [10.3390/app10124229](https://doi.org/10.3390/app10124229).
   *Baseline for neutralised lap-time ratios (≈140 % VSC, ≈160 % SC), the share of lap-1 Safety Cars, Safety-Car durations of 2–8 laps, and the warning that a full-course-yellow pit loss "cannot simply be halved".*
2. A. Heilmeier, A. Thomaser, M. Graf and J. Betz, "Virtual Strategy Engineer: Using artificial neural networks for making race strategy decisions in circuit motorsport," *Applied Sciences*, vol. 10, no. 21, art. 7805, 2020. doi: [10.3390/app10217805](https://doi.org/10.3390/app10217805).
   *Linear tyre-degradation baseline, and tyre ageing reduced by 50 % under VSC and 75 % under SC (our $\varphi_V,\varphi_S$).*
3. J. Bekker and W. Lotz, "Planning Formula One race strategies using discrete-event simulation," *Journal of the Operational Research Society*, vol. 60, no. 7, pp. 952–961, 2009.
   *Earlier discrete-event simulation of F1 strategy; context for the two-car team model.*
4. T. Tulabandhula and C. Rudin, "Tire changes, fresh air, and yellow flags: Challenges in predictive analytics for professional racing," *Big Data*, vol. 2, no. 2, pp. 97–112, 2014. doi: [10.1089/big.2014.0018](https://doi.org/10.1089/big.2014.0018).
   *Pit decisions under caution periods in NASCAR; the same "pit when neutralised" trade-off.*

## Simulation, Monte Carlo and statistics

5. A. M. Law, *Simulation Modeling and Analysis*, 5th ed. New York: McGraw-Hill, 2015. ISBN 978-0-07-340132-4.
   *Next-event time advance, input modelling, inverse-transform variate generation, common random numbers, confidence intervals and Bonferroni comparisons.*
6. P. Glasserman, *Monte Carlo Methods in Financial Engineering*. New York: Springer, 2003. doi: [10.1007/978-0-387-21617-1](https://doi.org/10.1007/978-0-387-21617-1).
   *Variance reduction with common random numbers; association argument for non-negative covariance (R11 in THEORY.md).*
7. G. E. P. Box and M. E. Muller, "A note on the generation of random normal deviates," *Annals of Mathematical Statistics*, vol. 29, no. 2, pp. 610–611, 1958. doi: [10.1214/aoms/1177706645](https://doi.org/10.1214/aoms/1177706645).
8. T. W. Anderson and L. A. Goodman, "Statistical inference about Markov chains," *Annals of Mathematical Statistics*, vol. 28, no. 1, pp. 89–110, 1957. doi: [10.1214/aoms/1177707039](https://doi.org/10.1214/aoms/1177707039).
   *Maximum-likelihood estimate of a transition matrix from transition counts.*
9. J. R. Norris, *Markov Chains*. Cambridge University Press, 1997. doi: [10.1017/CBO9780511810633](https://doi.org/10.1017/CBO9780511810633).
   *Stationary distributions, absorbing chains, renewal-reward arguments.*
10. A. Saltelli, M. Ratto, T. Andres, F. Campolongo, J. Cariboni, D. Gatelli, M. Saisana and S. Tarantola, *Global Sensitivity Analysis: The Primer*. Wiley, 2008. doi: [10.1002/9780470725184](https://doi.org/10.1002/9780470725184).
    *One-at-a-time and grid sensitivity designs, uncertainty propagation.*
11. B. Efron and R. J. Tibshirani, *An Introduction to the Bootstrap*. Chapman & Hall/CRC, 1993. doi: [10.1201/9780429246593](https://doi.org/10.1201/9780429246593).

## Numerical methods for ODEs

12. E. Hairer, S. P. Nørsett and G. Wanner, *Solving Ordinary Differential Equations I: Nonstiff Problems*, 2nd ed. Springer, 1993. doi: [10.1007/978-3-540-78862-1](https://doi.org/10.1007/978-3-540-78862-1).
    *Classical Runge–Kutta methods and their convergence orders (Euler 1, midpoint RK2 2, RK4 4).*
13. J. C. Butcher, *Numerical Methods for Ordinary Differential Equations*, 3rd ed. Wiley, 2016. doi: [10.1002/9781119121534](https://doi.org/10.1002/9781119121534).

## Data

14. Jolpica-F1, open-source successor of the Ergast motor-racing API: race results, lap times and pit stops. <https://github.com/jolpica/jolpica-f1>, API <https://api.jolpi.ca/ergast/f1/>. Data licence: CC BY-NC-SA 4.0 ([TERMS.md](https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md)). Accessed 24 Nov 2026.
15. OpenF1, open API for Formula 1 timing data (stints and compounds, pit stops, race-control messages). <https://openf1.org>. Licensed CC BY-NC-SA 4.0. Accessed 24 Nov 2026.
16. FastF1 documentation (timing-data field definitions used for the original design). <https://docs.fastf1.dev/>.
17. GPblog, "Pit lane speed limit raised in Singapore for strategy options," Oct. 2025. <https://www.gpblog.com/en/news/pit-lane-speed-limit-raised-in-singapore-for-strategy-options>.
18. Lights Out Blog, "Every Safety Car deployment at the Singapore Grand Prix." <https://www.lightsoutblog.com/every-safety-car-deployment-at-the-singapore-grand-prix>.

## Software

19. C. R. Harris *et al.*, "Array programming with NumPy," *Nature*, vol. 585, pp. 357–362, 2020. doi: [10.1038/s41586-020-2649-2](https://doi.org/10.1038/s41586-020-2649-2).
20. J. D. Hunter, "Matplotlib: A 2D graphics environment," *Computing in Science & Engineering*, vol. 9, no. 3, pp. 90–95, 2007. doi: [10.1109/MCSE.2007.55](https://doi.org/10.1109/MCSE.2007.55).
21. KaTeX, fast math typesetting for the web (MIT licence). <https://katex.org>.
